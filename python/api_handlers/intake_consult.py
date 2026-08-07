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
# GPT-loop runner was dead code since Phase 2.5 â€” target_seeking_orchestrator
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
# iter 19 Stage 5 â€” Python-first stage ramp builder + handler-on-failure.
# Replaces the GPT-only authoring path. The dependency-injection name
# stays `estimate_stage_ramp_contract_with_gpt` so the initial-grid
# runner's signature does not need to change; behind it, the new
# function tries the Python builder first and engages the stage ramp
# handler only when the validator rejects the deterministic output
# (doctrine.md Â§3 Pattern 2).
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
  taken (doctrine Â§1 hard-fail with diagnostic). P3.21 Part 2
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
    # Stage ramp handler exhausted. Per doctrine Â§1 hard-fail, surface
    # the diagnostic with the legacy GPT path as documentation of
    # what the alternative path used to do â€” but DO raise so the
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
# Listed explicitly â€” replacing the legacy globals()-as-source pattern
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
  """Phase 9 P3.10 Commit 5 Part B â€” failure-side outreach.

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
COMPETITIVE_ADVANTAGE_PREFIX = "Here's my working read of your competitive advantage:"
COMPETITIVE_ADVANTAGE_QUESTION = "Does that match what truly sets you apart, or is it something else?"
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
    "competitive_advantage",
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

  pending_clarify = persisted_financials.get("_basis_clarify_pending")
  resolution = persisted_financials.get("_basis_clarify_resolution")
  if isinstance(pending_clarify, dict) and isinstance(resolution, dict):
    # The client answered the basis question: land it at the source (ops
    # driver or the stage field), reassemble, and continue the flow.
    persisted_financials, persisted_year1, basis_ack = _apply_basis_clarify_resolution(
      conn=conn,
      draft_id=draft_id,
      resolution=resolution,
      pending=pending_clarify,
      financials_json=persisted_financials,
      financials_year1_json=persisted_year1,
      shared_context=dict(shared_context or {}),
      business_facts=business_facts,
    )
    if basis_ack:
      acknowledgement = basis_ack
    persisted_financials, persisted_year1, persisted_marketing = _persist_and_reload_financials_progress(
      conn=conn,
      draft_id=draft_id,
      business_facts=business_facts,
      financials_json=persisted_financials,
      financials_year1_json=persisted_year1,
      marketing_model_json=persisted_marketing or {},
    )
    pending_clarify = persisted_financials.get("_basis_clarify_pending")
  if isinstance(pending_clarify, dict) and pending_clarify:
    # Implausible unmarked-basis answer: ask ONE natural question before
    # building anything on it. The stage machine holds here until the
    # client answers (any phrasing routes; nothing requires literal words).
    clarify_turn = {
      "assistant_message": _build_basis_clarify_message(pending_clarify),
      "finalize_ready": False,
    }
    if str(acknowledgement or "").strip():
      clarify_turn["assistant_message"] = (
        f"{str(acknowledgement).strip()}\n\n{clarify_turn['assistant_message']}".strip()
      )
    return clarify_turn, persisted_financials, persisted_marketing

  # Reconcile BEFORE authoring the next stage message (issue #10): the
  # rescale used to run only at the top of the NEXT turn, so the cogs
  # anchor was authored on the pre-rescale driver total in the same call
  # frame the client stated revenue — 72% x $2.8M instead of 72% x $700k.
  synced_financials, synced_year1 = _sync_financials_consult_persistence_state(
    financials_json=persisted_financials,
    financials_year1_json=persisted_year1,
    marketing_model_json=persisted_marketing or {},
  )
  if synced_financials != persisted_financials or synced_year1 != persisted_year1:
    persisted_financials, persisted_year1, persisted_marketing = _persist_and_reload_financials_progress(
      conn=conn,
      draft_id=draft_id,
      business_facts=business_facts,
      financials_json=synced_financials,
      financials_year1_json=synced_year1,
      marketing_model_json=persisted_marketing or {},
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


def _resolve_display_utilization(operating_model: Dict[str, Any]) -> Optional[float]:
  """Representative utilization for display: top-level when present, else a
  capacity-weighted blend of the per-product rates under lob_models."""
  top_level = _safe_float((operating_model or {}).get("utilization_rate"))
  if top_level is not None:
    return top_level
  pairs: List[Tuple[float, Optional[float]]] = []
  for lob in (operating_model or {}).get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    for product in lob.get("products") or []:
      if not isinstance(product, dict):
        continue
      util = _safe_float(product.get("utilization_rate"))
      if util is None:
        continue
      weight = _safe_float(product.get("units_per_week_capacity"))
      if weight is None:
        weight = _safe_float(product.get("units_per_period_capacity"))
      pairs.append((util, weight))
  if not pairs:
    return None
  if all(weight is not None and weight > 0 for _, weight in pairs):
    total_weight = sum(weight for _, weight in pairs)
    return sum(util * weight for util, weight in pairs) / total_weight
  return sum(util for util, _ in pairs) / len(pairs)


def _build_financials_revenue_intro_message(
  *,
  intake_context: Dict[str, Any],
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> str:
  # Conversation-only revenue ask, branched on business_stage. No derived-revenue
  # table is shown mid-conversation; the capture path (revenue_intro stage patch on
  # current_revenue + done flag + post-intro rescale) is unchanged.
  stage = _financials_business_stage(shared_context)
  if stage == "operating":
    return (
      "Let's ground the plan in where the business is today: about how much revenue is "
      "the business bringing in a year right now? A rough annual figure is fine."
    )
  # early-stage (and unknown): permissive ask so a barely-started business can
  # answer "basically nothing yet" and flow to the derived-from-drivers path.
  return (
    "About how much is the business bringing in so far, if anything? A rough figure for "
    "the last year or your current run rate is fine, and it's completely fine if the "
    "answer is nothing yet."
  )


def _maybe_autocomplete_payroll_stage(
  financials_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Dict[str, Any]:
  """Payroll is no longer asked in Financials for any stage: startups derive it
  from key people + suggested roles, established businesses from key people +
  the rest-of-team figure captured in the People section. Stamp the derived
  total (the stage's completion field) so the stage machine advances without
  ever asking, mirroring the revenue_intro skip pattern."""
  next_financials = dict(financials_json or {})
  if _safe_float(next_financials.get("current_payroll")) is not None:
    return next_financials
  baseline = _compute_payroll_baseline(shared_context=shared_context)
  total = float(baseline.get("baseline_payroll_year1") or 0.0)
  next_financials["current_payroll"] = total
  next_financials["payroll_total_year1"] = total
  next_financials["baseline_payroll_year1"] = total
  next_financials["payroll_adjustment"] = 0.0
  next_financials["payroll_basis_people_roles"] = baseline.get("payroll_basis_people_roles") or []
  next_financials["_financials_payroll_stage_autofilled"] = "people-derived"
  return next_financials


def _maybe_autocomplete_revenue_intro(
  financials_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Dict[str, Any]:
  """Pre-revenue businesses are never asked for current revenue: there is none to
  state, and the model derives revenue from the ops drivers. Mark the revenue_intro
  stage done (same flag the stage's own patch path sets) so the stage machine
  advances cleanly instead of stalling on a question that will not be asked."""
  next_financials = dict(financials_json or {})
  if next_financials.get("_financials_revenue_intro_done"):
    return next_financials
  if _financials_business_stage(shared_context) == "pre-revenue":
    next_financials["_financials_revenue_intro_done"] = True
    next_financials["_financials_revenue_intro_skipped"] = "pre-revenue"
  return next_financials


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
      "About how much do you pay yourself from the business per month, all-in - salary plus any draws or other money you take? "
      "If you've already mentioned your own salary with the team, include it here rather than adding it on top. A rough figure is fine."
    )
  if stage == "other_operating_expense":
    return (
      "About how much goes to other regular business bills in a typical month, besides payroll, marketing, and rent - "
      "things like utilities, software, insurance, accounting, phone, and internet?"
    )
  if stage == "current_num_employees":
    return (
      "How many people are on payroll right now, not counting outside contractors? "
      "A whole number is fine."
    )
  if stage == "current_capex":
    return (
      "Have you recently made any larger one-time purchases for the business, like equipment, devices, furniture, build-out, or vehicles? "
      "If so, what was the rough total?"
    )
  if stage == "initial_assets":
    return (
      "What would you say the main equipment, devices, furniture, and fixtures currently in the business are worth, all together? A rough estimate is fine."
    )
  if stage == "initial_lease":
    return _build_initial_lease_message()
  if stage == "initial_equity":
    return (
      "Roughly how much money or value has gone into the business so far, from you or any investors, all together?"
    )
  if stage == "total_debt_outstanding":
    return (
      "About how much does the business currently owe in total on loans, lines of credit, or business credit cards?"
    )
  if stage == "other_monthly_debt_payments":
    return (
      "Besides regular rent and the credit card minimums already covered in other expenses, what other loan or debt payments does the business make each month?"
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
    return "About how much cash does the business have on hand right now, counting bank accounts and any cash on site?"
  if stage == "ar_balance":
    return (
      "About how much do customers currently owe you for completed work, like unpaid invoices or payment plans?"
    )
  if stage == "ap_balance":
    return (
      "About how much does the business currently owe in regular operating bills, like unpaid supplier invoices, utilities, or operations-related credit card balances?"
    )
  if stage == "inventory_balance":
    return (
      "About how much inventory do you have on hand right now, like products or supplies kept in stock to use or sell?"
    )
  if stage == "cash_strategy":
    return _build_cash_strategy_message()
  if stage == "funding_preference":
    return _build_funding_preference_message()
  if stage == "funding_split_debt_share":
    return _build_funding_split_message()
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
    return f"Got it. I’ll use direct costs of {total} a year ({percent} of revenue)."
  if stage == "current_payroll":
    return f"Got it. I’ll use payroll of {_format_currency((financials_json or {}).get('payroll_total_year1'))} a year."
  if stage == "marketing":
    total = _format_currency((financials_json or {}).get("marketing_total_year1"))
    percent = _format_percent((financials_json or {}).get("marketing_percent_of_revenue"))
    return f"Got it. I’ll use a marketing budget of {total} a year ({percent} of revenue)."
  if stage == "revenue_intro":
    return "Understood. We’ll build from your current revenue picture and move into the rest of the financials."
  if stage == "cash_strategy":
    return _build_cash_strategy_acknowledgement((financials_json or {}).get("cash_strategy"))
  if stage == "funding_preference":
    return _build_funding_preference_acknowledgement((financials_json or {}).get("funding_preference"))
  if stage == "funding_split_debt_share":
    return _build_funding_split_acknowledgement((financials_json or {}).get("funding_split_debt_share"))
  if stage == "current_num_employees":
    return f"Got it. I’ll use {int(round(float((financials_json or {}).get('current_num_employees') or 0)))} for current employee count."
  scalar_field = stage if stage in _GENERIC_FINANCIALS_FIELD_LABELS else ""
  if scalar_field:
    value = (financials_json or {}).get(stage)
    if stage == "future_rent_expected":
      return "Got it. I’ll treat future dedicated space as part of the model." if bool(value) else "Got it. I’ll treat future dedicated space as not expected for now."
    return _build_financials_scalar_stage_acknowledgement(stage, float(value or 0.0))
  return "Got it."


def _receipt_echo_line(before_json: Dict[str, Any], after_json: Dict[str, Any], domain: str) -> str:
  """Layer 2: deterministic echo of what an apply ACTUALLY changed in one
  domain - appended to GPT prose so every numeric write is said, from the
  write-set, never from intent. Empty string when nothing changed."""
  try:
    from client_intake_and_finmo.capture_receipt import numeric_receipt, receipt_summary  # type: ignore

    receipt = numeric_receipt(before={domain: before_json or {}}, after={domain: after_json or {}})
    return receipt_summary(receipt)
  except Exception:
    return ""


def _build_financials_stage_acknowledgement_first(
  router_text: Any,
  *,
  stage_name: str,
  financials_json: Dict[str, Any],
) -> str:
  """Layer 2 preference order: the acknowledgment BUILT FROM THE APPLIED
  VALUES wins; the router's free prose is fallback only. Prose is a
  sibling output of the interpretation call and can quote a figure the
  whitelist dropped - the applied-values ack cannot, because it reads the
  post-write state."""
  code_ack = _build_financials_stage_acknowledgement(
    stage_name=stage_name, financials_json=financials_json,
  )
  if code_ack and code_ack != "Got it.":
    return code_ack
  return str(router_text or "").strip() or code_ack


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
  next_financials = _maybe_autocomplete_revenue_intro(next_financials, shared_context)
  next_financials = _maybe_autocomplete_payroll_stage(next_financials, shared_context)
  next_stage = _next_financials_stage(next_financials)
  if not next_stage:
    return _build_financials_completion_turn(), next_financials

  next_context = dict(intake_context or {})
  next_context["financials_json"] = next_financials
  next_shared = dict(shared_context or {})
  next_shared["financials"] = next_financials
  next_shared["financials_controller"] = _build_financials_controller_context(next_stage, financials_json=next_financials)
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
    f"For direct costs - things like materials, supplies, and other costs tied directly to delivering the work - a reasonable starting point is about "
    f"{_format_percent(cogs_baseline.get('baseline_cogs_percent'))} of revenue, which works out to around "
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


def _rest_of_team_payroll_pending(
  people_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> bool:
  """Established businesses (business_stage 'operating', or missing/ambiguous -
  the safe default) state one rest-of-team payroll figure before People wraps.
  Startups (pre-revenue / early-stage) keep the suggested-roles flow and are
  never asked."""
  stage = str((ops_json or {}).get("business_stage") or "").strip().lower()
  if stage in ("pre-revenue", "early-stage"):
    return False
  return _safe_float((people_json or {}).get("rest_of_team_payroll_year1")) is None


# Distinctive phrase present in BOTH the question and its re-ask, so the router
# keeps its controller frame across retries. Matches the app's own deterministic
# text only - never client language, which is always GPT-interpreted by intent.
_REST_OF_TEAM_PAYROLL_MARKER = "payroll for the rest of your team"


def _build_rest_of_team_payroll_question(acknowledgement: str = "") -> str:
  question = (
    "Beyond yourself and the key people we just covered, roughly what does "
    f"{_REST_OF_TEAM_PAYROLL_MARKER} come to per year? A rough annual figure is "
    "fine - and it's fine if there isn't anyone else on payroll."
  )
  ack = str(acknowledgement or "").strip()
  return f"{ack}\n\n{question}".strip() if ack else question


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

  # Established businesses state one rest-of-team payroll figure (captured in the
  # People section, explicitly EXCLUDING the owner and key people already counted
  # above) instead of the suggested-roles flow. Add it exactly once, here - this
  # function is the single summing point that stamps payroll_total_year1.
  rest_of_team = _safe_float(people_context.get("rest_of_team_payroll_year1"))
  if rest_of_team is not None and rest_of_team > 0:
    baseline_total += float(rest_of_team)
    basis_roles.append(
      {
        "source": "rest_of_team_payroll",
        "role_title": "Rest of team (client-stated total)",
        "annual_wage": float(rest_of_team),
        "months_counted_year1": 12,
        "year1_payroll_amount": float(rest_of_team),
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
      "This payroll estimate reflects the team needed to launch and operate over the next year, including any planned hires from the staffing plan."
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
    f"Based on the team we mapped out together, payroll comes to about "
    f"{_format_currency(payroll_baseline.get('baseline_payroll_year1'))} across {role_count} {role_phrase} in the plan.\n\n"
    f"{clarification}{composition}\n\n"
    "Does that broadly match what you expect to spend on payroll over the next year, or should we adjust it because your actual setup is materially different?"
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
    f"For marketing, a reasonable starting point is about "
    f"{_format_percent(marketing_baseline.get('baseline_marketing_percent'))} of revenue, which works out to around "
    f"{_format_currency(marketing_baseline.get('baseline_marketing'))} a year.\n\n"
    "Does that broadly match what it will take to attract and convert customers, or should we adjust it because your marketing spend will be materially different?"
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
  # The TOTAL is the client-stated fact; the percent is DERIVED - always
  # recompute it (mirroring the cogs family). Keeping a co-present percent
  # untouched let a router-emitted monthly-numerator ratio survive next to
  # a correctly annualized total (CW-007: $42,000/yr stored with
  # percent=0.004655 = monthly/annual, exactly 1/12 of the true 0.0559 -
  # silent, and anything reading the ratio saw ~$3,500/yr).
  if total is not None and revenue and revenue > 0:
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
  field_name = str(field or "").strip()
  if field_name == "funding_split_debt_share":
    # The split only applies when the client wants BOTH debt and equity;
    # a debt-only or equity-only preference resolves (skips) this stage.
    preference = str(financials_json.get("funding_preference") or "").strip().lower()
    if preference in ("debt", "equity"):
      return True
    return _funding_split_share_value(financials_json.get(field_name)) is not None
  if field not in financials_json:
    return False
  if field_name == "cash_strategy":
    return _cash_strategy_option(financials_json.get(field)) is not None
  if field_name == "funding_preference":
    return _funding_preference_option(financials_json.get(field)) is not None
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
  "funding_preference",
  "funding_split_debt_share",
)


_FINANCIALS_STAGE_SPECS: Dict[str, Dict[str, Any]] = {
  "revenue_intro": {
    "patch_targets": ("current_revenue",),
    "completion_fields": ("_financials_revenue_intro_done",),
    "confirmable_baseline": True,
    "clarifier": "What annual revenue number should I use as the starting point instead?",
  },
  "cogs": {
    "patch_targets": ("current_cogs", "cogs_total_year1", "cogs_percent_of_revenue"),
    "completion_fields": ("current_cogs",),
    "confirmable_baseline": True,
    "clarifier": "What annual direct-cost amount or percent of revenue should I use instead?",
  },
  "current_payroll": {
    "patch_targets": ("current_payroll", "payroll_total_year1"),
    "completion_fields": ("current_payroll",),
    "confirmable_baseline": True,
    "clarifier": "What annual payroll should I use instead?",
  },
  "marketing": {
    "patch_targets": ("marketing_total_year1", "marketing_percent_of_revenue"),
    # Completion is an explicit stage-done flag (same pattern as revenue_intro):
    # marketing_total_year1 can be materialized by field-family syncing before
    # this stage ever runs, and a pre-existing value must not skip the question.
    "completion_fields": ("_financials_marketing_stage_done",),
    "confirmable_baseline": True,
    "clarifier": "What annual marketing budget or percent of revenue should I use instead?",
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
    "clarifier": "What total monthly owner pay - salary plus draws, all-in - should I record?",
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
  "funding_preference": {
    "patch_targets": ("funding_preference",),
    "completion_fields": ("funding_preference",),
    "confirmable_baseline": False,
    "clarifier": "Which funding approach should I record: Debt, Equity, or Both?",
  },
  "funding_split_debt_share": {
    "patch_targets": ("funding_split_debt_share",),
    "completion_fields": ("funding_split_debt_share",),
    "confirmable_baseline": False,
    "clarifier": "Which debt-to-equity mix should I record: mostly debt (about 70/30), an even split (50/50), or mostly equity (about 30/70)?",
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


_FUNDING_PREFERENCE_OPTIONS: Tuple[Dict[str, str], ...] = (
  {
    "value": "debt",
    "label": "Debt",
    "description": "Borrowed money, like bank loans or lines of credit, repaid over time.",
  },
  {
    "value": "equity",
    "label": "Equity",
    "description": "Owner or investor money put into the business, with no required repayment schedule.",
  },
  {
    "value": "both",
    "label": "Both",
    "description": "A deliberate mix of debt and equity working together.",
  },
)

_FUNDING_SPLIT_OPTIONS: Tuple[Dict[str, Any], ...] = (
  {
    "value": 0.70,
    "label": "Mostly debt",
    "description": "About 70/30 debt-to-equity.",
  },
  {
    "value": 0.50,
    "label": "Even split",
    "description": "About 50/50 debt-to-equity.",
  },
  {
    "value": 0.30,
    "label": "Mostly equity",
    "description": "About 30/70 debt-to-equity.",
  },
)


def _funding_preference_option(value: Any) -> Optional[Dict[str, str]]:
  normalized = str(value or "").strip().lower()
  if not normalized:
    return None
  for option in _FUNDING_PREFERENCE_OPTIONS:
    if normalized == option["value"]:
      return dict(option)
  return None


def _funding_split_share_value(value: Any) -> Optional[float]:
  """Normalize a debt-share answer to one of the persisted split values.

  Accepts a ratio (0.7), a percentage (70), and snaps off-menu values to the
  nearest allowed option, mirroring the post-intake reader's snapping."""
  numeric = _safe_float(value)
  if numeric is None:
    return None
  if 1.0 < numeric <= 100.0:
    numeric = numeric / 100.0
  if numeric <= 0.0 or numeric >= 1.0:
    return None
  return min(
    (float(option["value"]) for option in _FUNDING_SPLIT_OPTIONS),
    key=lambda allowed: abs(allowed - numeric),
  )


def _format_funding_options(options: Tuple[Dict[str, Any], ...]) -> str:
  return "\n".join(f"- {option['label']}: {option['description']}" for option in options)


def _build_funding_preference_message() -> str:
  return (
    "One more planning question on funding: when this business needs outside capital to operate or grow, "
    "how would you prefer to fund it?\n\n"
    + _format_funding_options(_FUNDING_PREFERENCE_OPTIONS)
    + "\n\nYou can answer in plain language and I'll map it to the closest approach."
  )


def _build_funding_split_message() -> str:
  return (
    "Since you'd use both debt and equity, roughly what mix feels right for planning?\n\n"
    + _format_funding_options(_FUNDING_SPLIT_OPTIONS)
    + "\n\nA rough answer is fine, and we'll treat it as a planning assumption you can revisit."
  )


def _build_funding_preference_acknowledgement(value: Any) -> str:
  option = _funding_preference_option(value)
  if not option:
    return "Got it."
  if option["value"] == "both":
    return "Got it - I'll plan on funding the business with a mix of debt and equity."
  return f"Got it - I'll plan on funding the business primarily with {option['label'].lower()}."


def _build_funding_split_acknowledgement(value: Any) -> str:
  share = _funding_split_share_value(value)
  if share is None:
    return "Got it."
  split_label = {0.70: "70/30", 0.50: "50/50", 0.30: "30/70"}.get(round(share, 2), f"{share:.0%} debt")
  return f"Got it - I'll use roughly a {split_label} debt-to-equity mix as the planning split."


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


def _build_financials_controller_context(stage_name: Optional[str], *, last_assistant: str = "", financials_json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
  from client_intake_and_finmo.field_basis import basis_of  # type: ignore

  stage = str(stage_name or "").strip()
  spec = _financials_stage_spec(stage)
  patch_targets = list(spec.get("patch_targets") or [])
  current_stage = {
    "name": stage or None,
    "patch_targets": patch_targets,
    "completion_fields": list(spec.get("completion_fields") or []),
    "confirmable_baseline": bool(spec.get("confirmable_baseline")),
    "clarifier": str(spec.get("clarifier") or "").strip(),
    # Declared stored-basis per patch target (field_basis registry): the
    # router normalizes the client's stated basis to this — convert, never
    # copy. The ONLY basis authority; no apply-layer conversions exist.
    "basis": {field: basis_of(field) for field in patch_targets},
  }
  if stage == "cash_strategy":
    current_stage["allowed_values"] = [option["value"] for option in _CASH_STRATEGY_OPTIONS]
    current_stage["options"] = [dict(option) for option in _CASH_STRATEGY_OPTIONS]
    current_stage["decision_mode"] = _cash_strategy_decision_mode(last_assistant)
  if stage == "funding_preference":
    current_stage["allowed_values"] = [option["value"] for option in _FUNDING_PREFERENCE_OPTIONS]
    current_stage["options"] = [dict(option) for option in _FUNDING_PREFERENCE_OPTIONS]
  if stage == "funding_split_debt_share":
    current_stage["allowed_values"] = [option["value"] for option in _FUNDING_SPLIT_OPTIONS]
    current_stage["options"] = [dict(option) for option in _FUNDING_SPLIT_OPTIONS]
  frame: Dict[str, Any] = {"current_stage": current_stage}
  pending = (financials_json or {}).get("_basis_clarify_pending")
  if isinstance(pending, dict) and pending:
    # An app-authored basis question is in flight: the client's reply
    # answers THAT, whatever words they use. Declares the semantics for
    # the router; nothing here keys on phrasing.
    _kind = str(pending.get("kind") or "")
    if _kind == "percent_vs_dollar":
      allowed = ["percent", "dollars", "as_stated"]
    elif _kind == "driver_price_scope":
      allowed = ["weekly", "monthly", "annual", "as_stated"]
    else:
      allowed = ["weekly", "monthly", "annual", "as_stated"]
    frame["pending_basis_clarify"] = {
      "question": _basis_clarify_closed_question(pending),
      "kind": _kind,
      "asked_basis": str(pending.get("asked_basis") or ""),
      "candidate_basis": str(pending.get("candidate_basis") or ""),
      "stated_value": pending.get("stated_value"),
      "allowed_bases": allowed,
    }
  return frame


def _financials_stage_confirm_question(stage_name: Optional[str]) -> Optional[str]:
  spec = _financials_stage_spec(stage_name)
  if not bool(spec.get("confirmable_baseline")):
    return None
  stage = str(stage_name or "").strip()
  if stage == "revenue_intro":
    return "Should I use this revenue figure as the starting point for the plan?"
  if stage == "cogs":
    return "Should I use this direct-cost baseline?"
  if stage == "current_payroll":
    return "Should I use this payroll baseline?"
  if stage == "marketing":
    return "Should I use this marketing baseline?"
  return None


# ---------------------------------------------------------------------------
# Unmarked-basis capture class (issues #24/#25/#10/#26, Bridgeburn run):
# a client answer whose inferred value is WILDLY inconsistent with a figure
# the client already gave must trigger a natural clarifier, never silently
# land. The trigger is IMPLAUSIBILITY (a period-conversion fingerprint), not
# every unmarked number — intake stays a conversation, not an interrogation.
# ---------------------------------------------------------------------------

_BASIS_PERIODS_PER_YEAR = {"weekly": 52.0, "monthly": 12.0, "annual": 1.0}

# ratio of driver-implied to stated revenue that fingerprints one specific
# misread: (asked basis, actually-meant basis) -> implied/stated ratio.
_BASIS_FINGERPRINTS: Tuple[Tuple[str, str, float], ...] = (
  ("weekly", "monthly", 52.0 / 12.0),
  ("weekly", "annual", 52.0),
  ("monthly", "annual", 12.0),
  ("monthly", "weekly", 12.0 / 52.0),
  ("annual", "monthly", 1.0 / 12.0),
  ("annual", "weekly", 1.0 / 52.0),
)
_BASIS_FINGERPRINT_TOLERANCE = 0.15


def _detect_revenue_driver_basis_conflict(
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  """Driver-implied revenue vs client-stated revenue: when the ratio matches
  a period-conversion fingerprint (x4.33 weekly/monthly, x12, x52), the most
  likely truth is a basis misread on the dominant product's unit price — the
  Bridgeburn client's monthly $1,100 recorded as weekly implied $2.8M against
  a stated $700k (ratio 4.02 ~ 52/12). Returns the pending-clarify payload or
  None when nothing is implausible."""
  stated = _safe_float((financials_json or {}).get("current_revenue")) or 0.0
  implied = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1")) or 0.0
  if stated <= 0.0 or implied <= 0.0:
    return None
  ratio = implied / stated
  if 0.87 <= ratio <= 1.15:
    return None  # agree closely; the silent rescale handles the residue
  if 0.5 <= ratio < 0.87:
    return None  # mildly under-implied: not a basis fingerprint shape
  match = None
  for asked, meant, fingerprint in _BASIS_FINGERPRINTS:
    if abs(ratio - fingerprint) / fingerprint <= _BASIS_FINGERPRINT_TOLERANCE:
      match = (asked, meant)
      break
  if match is None:
    # PER-PRODUCT probe (CW-007 #31): one product misread by a period
    # fingerprint while the others are fine blends the company ratio away
    # from any fingerprint (Bluebird's annual membership stored at monthly
    # cadence inflated ONE line x12). If rescaling a single product by one
    # fingerprint reconciles implied to stated (within 15%), that product
    # is the suspect.
    if ratio <= 1.15:
      return None
    for lob in (financials_year1_json or {}).get("lobs") or []:
      if not isinstance(lob, dict):
        continue
      for product in lob.get("products") or []:
        if not isinstance(product, dict):
          continue
        prod_rev = _safe_float(product.get("revenue_total_year1")) or 0.0
        if prod_rev <= 0 or _safe_float(product.get("unit_price")) is None:
          continue
        for asked, meant, fingerprint in _BASIS_FINGERPRINTS:
          if fingerprint <= 1.0:
            continue
          if str(product.get("unit_cadence") or "").strip().lower() != asked:
            continue
          adjusted = implied - prod_rev + (prod_rev / fingerprint)
          if adjusted > 0 and abs(adjusted / stated - 1.0) <= 0.15:
            return {
              "kind": "driver_price",
              "lob_name": str(lob.get("lob_name") or "").strip(),
              "product_name": str(product.get("product_name") or "").strip(),
              "unit_name": str(product.get("unit_name") or "").strip(),
              "stated_value": float(_safe_float(product.get("unit_price")) or 0.0),
              "asked_basis": asked,
              "candidate_basis": meant,
              "implied_revenue": float(implied),
              "stated_revenue": float(stated),
              "ratio": float(ratio),
            }
    # SCOPE probe (CW-007 #28): no period fingerprint fits company-wide or
    # per-product, but ONE product carries most of the excess - the stated
    # figure is likely a per-ENGAGEMENT total recorded as a per-period rate
    # (Brightwater's "$9,500 a typical matter" -> $9,500/matter/month,
    # ratio 1.97, under every period fingerprint). Propose-confirm; the
    # client restates the per-period amount or confirms as stated.
    if ratio >= 1.5:
      excess = implied - stated
      dominant = None
      for lob in (financials_year1_json or {}).get("lobs") or []:
        if not isinstance(lob, dict):
          continue
        for product in lob.get("products") or []:
          if not isinstance(product, dict):
            continue
          prod_rev = _safe_float(product.get("revenue_total_year1")) or 0.0
          if prod_rev >= 0.6 * excess and _safe_float(product.get("unit_price")) is not None:
            if dominant is None or prod_rev > (_safe_float(dominant[1].get("revenue_total_year1")) or 0.0):
              dominant = (lob, product)
      if dominant is not None:
        lob, product = dominant
        return {
          "kind": "driver_price_scope",
          "lob_name": str(lob.get("lob_name") or "").strip(),
          "product_name": str(product.get("product_name") or "").strip(),
          "unit_name": str(product.get("unit_name") or "").strip(),
          "stated_value": float(_safe_float(product.get("unit_price")) or 0.0),
          "asked_basis": str(product.get("unit_cadence") or "").strip().lower() or "monthly",
          "candidate_basis": "per_engagement_total",
          "implied_revenue": float(implied),
          "stated_revenue": float(stated),
          "ratio": float(ratio),
        }
    return None
  # The misread lives in ONE driver; name the dominant revenue contributor
  # whose cadence matches the fingerprint's asked basis.
  dominant: Optional[Dict[str, Any]] = None
  for lob in (financials_year1_json or {}).get("lobs") or []:
    if not isinstance(lob, dict):
      continue
    for product in lob.get("products") or []:
      if not isinstance(product, dict):
        continue
      cadence = str(product.get("unit_cadence") or "").strip().lower()
      if cadence != match[0]:
        continue
      revenue = _safe_float(product.get("revenue_total_year1")) or 0.0
      if dominant is None or revenue > (_safe_float(dominant.get("revenue_total_year1")) or 0.0):
        dominant = dict(product)
        dominant["_lob_name"] = str(lob.get("lob_name") or "").strip()
  if dominant is None or _safe_float(dominant.get("unit_price")) is None:
    return None
  return {
    "kind": "driver_price",
    "lob_name": dominant.get("_lob_name") or "",
    "product_name": str(dominant.get("product_name") or "").strip(),
    "unit_name": str(dominant.get("unit_name") or "").strip(),
    "stated_value": float(_safe_float(dominant.get("unit_price")) or 0.0),
    "asked_basis": match[0],
    "candidate_basis": match[1],
    "implied_revenue": float(implied),
    "stated_revenue": float(stated),
    "ratio": float(ratio),
  }


def _detect_stage_amount_basis_conflict(
  *,
  field_name: str,
  financials_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  """Annual-basis stage amount implausibly small against stated revenue:
  the Bridgeburn client's monthly $1,500 marketing landed as $1,500/YEAR —
  0.21% of revenue, a 56x drop from the proposed anchor, unclarified. Fires
  only when the annual reading is tiny (<0.5% of revenue) AND the monthly
  reading is ordinary (>=1%) — a genuinely tiny annual spend answers the
  one question and proceeds."""
  value = _safe_float((financials_json or {}).get(field_name)) or 0.0
  revenue = _safe_float((financials_json or {}).get("current_revenue")) or 0.0
  if value <= 0.0 or revenue <= 0.0:
    return None
  annual_share = value / revenue
  monthly_share = (value * 12.0) / revenue
  if annual_share >= 0.005 or monthly_share < 0.01:
    return None
  return {
    "kind": "stage_amount",
    "field": field_name,
    "stated_value": float(value),
    "asked_basis": "annual",
    "candidate_basis": "monthly",
    "stated_revenue": float(revenue),
  }


def _detect_percent_vs_dollar_conflict(
  *,
  field_name: str,
  percent_value: float,
  financials_json: Dict[str, Any],
  user_message: str,
) -> Optional[Dict[str, Any]]:
  """A bare figure after a percent anchor is ambiguous: "about fourteen"
  can mean 14% of revenue (~$103k) or about $14,000 (CW-007 #32). Fires
  ONLY when the client marked neither unit AND both readings are plausible
  AND they differ materially - a marked answer ("14%", "$14k") or an
  implausible alternative reading never asks."""
  msg = str(user_message or "").lower()
  if "%" in msg or "percent" in msg or "$" in msg or "dollar" in msg:
    return None
  revenue = _safe_float((financials_json or {}).get("current_revenue")) or 0.0
  if revenue <= 0 or percent_value <= 0.005 or percent_value > 1.0:
    return None
  raw_number = percent_value * 100.0  # "fourteen" -> 0.14 -> 14
  percent_reading = percent_value * revenue
  dollar_reading = raw_number * 1000.0  # the natural founder shorthand
  if dollar_reading < 0.002 * revenue or dollar_reading > 0.5 * revenue:
    return None  # the dollar reading is implausible; percent stands
  bigger, smaller = max(percent_reading, dollar_reading), min(percent_reading, dollar_reading)
  if smaller <= 0 or bigger / smaller < 3.0:
    return None  # readings agree closely enough that it doesn't matter
  return {
    "kind": "percent_vs_dollar",
    "field": field_name,
    "stated_value": float(percent_value),
    "percent_reading_dollars": float(percent_reading),
    "dollar_reading": float(dollar_reading),
    "stated_revenue": float(revenue),
  }


_SMALL_NUMBER_WORDS = {
  "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
  "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
  "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
  "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
  "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
  "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _percent_shaped_figures(message: str) -> List[float]:
  """Bare figures in a client message that COULD be a percent: digit tokens
  and simple number words (incl. 'twenty five' compounds), 0.5-100 only."""
  msg = str(message or "").lower().replace(",", "")
  out: List[float] = []
  for tok in re.findall(r"\d+(?:\.\d+)?", msg):
    try:
      n = float(tok)
    except ValueError:
      continue
    if 0.5 <= n <= 100.0:
      out.append(n)
  words = re.findall(r"[a-z]+", msg)
  index = 0
  while index < len(words):
    word = words[index]
    if word in _SMALL_NUMBER_WORDS:
      n = float(_SMALL_NUMBER_WORDS[word])
      if n >= 20 and index + 1 < len(words) and words[index + 1] in _SMALL_NUMBER_WORDS \
         and _SMALL_NUMBER_WORDS[words[index + 1]] < 10:
        n += float(_SMALL_NUMBER_WORDS[words[index + 1]])
        index += 1
      if 0.5 <= n <= 100.0:
        out.append(n)
    index += 1
  return out


def _detect_dollar_vs_percent_conflict(
  *,
  field_name: str,
  dollar_value: float,
  financials_json: Dict[str, Any],
  user_message: str,
) -> Optional[Dict[str, Any]]:
  """The REVERSE of _detect_percent_vs_dollar_conflict (CW-009 checkpoint-a
  gap): when the router reads an unmarked bare figure as DOLLARS and writes
  a cost total ("we're at about twelve" -> marketing_total_year1=12,000),
  no percent field is ever written, so the forward detector cannot run.
  Fires ONLY when the client marked no unit, a percent-shaped raw figure
  (<=100) in their message is what the router scaled into the total
  (founder shorthand: n -> $n,000), the percent reading is itself
  plausible, and the two readings diverge >=3x. Emits the SAME pending
  kind and shape as the forward detector - one clarifier, one resolution
  path, direction carried in 'recorded'."""
  msg = str(user_message or "").lower()
  if "%" in msg or "percent" in msg or "$" in msg or "dollar" in msg:
    return None
  if "thousand" in msg or "grand" in msg or re.search(r"\b\d+(?:\.\d+)?k\b", msg):
    return None  # explicitly dollar-shaped shorthand
  revenue = _safe_float((financials_json or {}).get("current_revenue")) or 0.0
  total = _safe_float(dollar_value) or 0.0
  if revenue <= 0 or total <= 0:
    return None
  raw_number = None
  for n in _percent_shaped_figures(msg):
    if abs(total - n * 1000.0) <= max(1.0, 0.005 * total):
      raw_number = n
      break
  if raw_number is None:
    return None  # the written total didn't come from a percent-shaped figure
  percent_value = raw_number / 100.0
  if percent_value < 0.005 or percent_value > 0.5:
    return None  # the percent alternative is implausible; dollars stand
  percent_reading = percent_value * revenue
  bigger, smaller = max(percent_reading, total), min(percent_reading, total)
  if smaller <= 0 or bigger / smaller < 3.0:
    return None  # readings agree closely enough that it doesn't matter
  percent_twin = field_name.replace("_total_year1", "_percent_of_revenue")
  return {
    "kind": "percent_vs_dollar",
    "field": percent_twin,
    "recorded": "dollars",
    "stated_value": float(percent_value),
    "percent_reading_dollars": float(percent_reading),
    "dollar_reading": float(total),
    "stated_revenue": float(revenue),
  }


def _prose_reflection_needed(
  *,
  old_value: str,
  new_value: str,
  assistant_text: str,
  user_message: str,
) -> bool:
  """CW-011 #3: the prose receipt fires when a tracked proposal field
  changed from a prior non-empty value on a substantive client turn AND
  the consultant's own reply does not already reflect the stored content
  (checked via the stored value's distinctive words - when the GPT
  complied with the prompt rule, no double-reflection)."""
  old = str(old_value or "").strip()
  new = str(new_value or "").strip()
  if not (old and new) or new == old:
    return False
  if len(str(user_message or "").strip()) <= 20:
    return False
  distinct = re.findall(r"[a-zA-Z-]{8,}", new)[:6]
  text = str(assistant_text or "").lower()
  if distinct and any(w.lower() in text for w in distinct):
    return False
  return True


def _message_figures(message: str) -> List[float]:
  """Every numeric figure in a client message: digits (comma-stripped),
  k/thousand shorthand expanded, and small number words."""
  msg = str(message or "").lower().replace(",", "")
  out: List[float] = []
  for tok, k_suffix in re.findall(r"(\d+(?:\.\d+)?)(\s*k\b)?", msg):
    try:
      n = float(tok)
    except ValueError:
      continue
    out.append(n * 1000.0 if k_suffix.strip() else n)
  for m in re.finditer(r"(\d+(?:\.\d+)?)\s+thousand", msg):
    out.append(float(m.group(1)) * 1000.0)
  out.extend(_percent_shaped_figures(msg))
  return out


def _find_numeric_leaf_value(obj: Any, leaf: str) -> Optional[float]:
  """First numeric value stored under `leaf` anywhere in a JSON-ish
  structure (dicts/lists, e.g. lob_models products)."""
  if isinstance(obj, dict):
    for k, v in obj.items():
      if str(k) == leaf and isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
      found = _find_numeric_leaf_value(v, leaf)
      if found is not None:
        return found
  elif isinstance(obj, list):
    for item in obj:
      found = _find_numeric_leaf_value(item, leaf)
      if found is not None:
        return found
  return None


_DRIVER_LEVER_LEAVES = (
  "unit_price",
  "units_per_period_capacity",
  "units_per_week_capacity",
  "operating_periods_per_year",
  "utilization_rate",
)


def _lever_value_derivable(
  leaf: str, value: Any, figures: List[float], periods: float
) -> bool:
  """CW-011 consequence contract: a driver-lever write is legitimate ONLY
  if its new value is arithmetically derivable from the figures the
  client actually stated - raw, unit-converted by the period count, or
  (for utilization) as a ratio of two stated figures (did 16 / turns 22
  = 72.7%). CW-011's 0.9167 (= 22/24, where 24 appears nowhere in the
  client's words) fails and reverts; 1.833 (= 22/12) passes."""
  v = _safe_float(value)
  if v is None:
    return True
  figs = [f for f in figures if f and f > 0]
  if not figs:
    return False

  def near(a: float, b: float, tol: float = 0.02) -> bool:
    return abs(a - b) / max(abs(b), 1e-9) <= tol

  cands: List[float] = []
  if leaf in ("units_per_period_capacity", "units_per_week_capacity"):
    for f in figs:
      cands.append(f)
      if periods:
        cands.append(f / periods)
      cands.append(f / 52.0)
  elif leaf == "operating_periods_per_year":
    cands = list(figs)
  elif leaf == "utilization_rate":
    # CW-012 (a): "one" from "my one-a-month guess" legitimized
    # utilization 1.0 via the old raw f<=1.0 branch - the synthetic
    # tooth message had no figure equal to 1.0 so teeth passed while
    # live failed. Bare small integers are counts or number words,
    # never utilization statements: accept only non-integer decimals
    # ("0.75"), percent-shaped figures above 2 ("75" -> 0.75), and
    # ratios of two stated figures (did 16 / turns 22 -> 72.7%).
    for f in figs:
      if f <= 1.0 and abs(f - round(f)) > 1e-9:
        cands.append(f)
      if 2.0 < f <= 100.0:
        cands.append(f / 100.0)
    for a in figs:
      for b in figs:
        if b > 0 and a < b:
          cands.append(a / b)
  elif leaf == "unit_price":
    for f in figs:
      cands.append(f)
      cands.append(f * 1000.0)
  else:
    return True
  return any(near(v, c) for c in cands if c and c > 0)


def _reconcile_driver_correction(
  *,
  ops_before: Dict[str, Any],
  ops_after: Dict[str, Any],
  user_message: str,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
  """The CW-011 consequence contract, enforced in code: a driver
  correction may move ONLY levers derivable from the client's own
  figures. Any other lever write REVERTS to its prior (client-stated)
  value before the receipt or ack is composed - never a silent second
  lever. Returns (ops_fixed, note) where note carries the changed
  product's implied stream in dollars (anchored to the client's stated
  stream figure when one matches within 5%) and, on the RARE case the
  named-only fit misses the client's own stated dollars by >5%, a
  disclose-and-confirm question instead of a silent re-fit."""
  figures = _message_figures(user_message)
  if not figures or not isinstance(ops_after, dict):
    return ops_after, None
  before_lobs = (ops_before or {}).get("lob_models") or []
  after_lobs = ops_after.get("lob_models") or []
  if not (isinstance(before_lobs, list) and isinstance(after_lobs, list)):
    return ops_after, None
  reverted: List[Tuple[str, float, float]] = []
  changed_products: List[Dict[str, Any]] = []
  for lob_i, lob_after in enumerate(after_lobs):
    if not isinstance(lob_after, dict) or lob_i >= len(before_lobs):
      continue
    lob_before = before_lobs[lob_i] if isinstance(before_lobs[lob_i], dict) else {}
    prods_after = lob_after.get("products") or []
    prods_before = lob_before.get("products") or []
    for p_i, p_after in enumerate(prods_after):
      if not isinstance(p_after, dict) or p_i >= len(prods_before):
        continue
      p_before = prods_before[p_i] if isinstance(prods_before[p_i], dict) else {}
      periods = _safe_float(p_after.get("operating_periods_per_year")) or \
        _safe_float(p_before.get("operating_periods_per_year")) or 12.0
      touched_here = False
      for leaf in _DRIVER_LEVER_LEAVES:
        old_v = _safe_float(p_before.get(leaf))
        new_v = _safe_float(p_after.get(leaf))
        if new_v is None or old_v is None:
          continue
        if abs(new_v - old_v) <= max(1e-9, 0.001 * abs(old_v)):
          continue
        touched_here = True
        if not _lever_value_derivable(leaf, new_v, figures, periods):
          p_after[leaf] = old_v
          reverted.append((leaf, new_v, old_v))
      if touched_here:
        changed_products.append(
          {"before": p_before, "after": p_after, "lob_index": lob_i, "product_index": p_i}
        )
  if not changed_products:
    # CW-012 turn-115 shape: the router model rounds the asked value to
    # what is ALREADY stored (2.5 -> 2), so no product is touched at all
    # and the correction vanishes without a trace - four differently-
    # worded asks failed this way. When the message carries a coherent
    # triplet against a product's KEPT price and utilization (count x
    # price x util ~= stated dollars) and that product's current stream
    # MISSES the stated dollars, land capacity = count / periods here.
    # Three cohering numbers against stored values is a strong enough
    # fingerprint that unrelated financial answers never match.
    count_figs = [f for f in figures if 1.0 < f <= 2000.0 and abs(f - round(f)) < 1e-6]
    dollar_figs = [f for f in figures if f >= 1000.0]
    for lob_i, lob_after in enumerate(after_lobs):
      if not isinstance(lob_after, dict):
        continue
      for p_i, p_after in enumerate(lob_after.get("products") or []):
        if not isinstance(p_after, dict):
          continue
        price0 = _safe_float(p_after.get("unit_price")) or 0.0
        periods0 = _safe_float(p_after.get("operating_periods_per_year")) or 12.0
        util0 = _safe_float(p_after.get("utilization_rate"))
        util0 = util0 if util0 and 0.0 < util0 <= 1.0 else 1.0
        cap0 = _safe_float(p_after.get("units_per_period_capacity")) or 0.0
        stream0 = price0 * cap0 * periods0 * util0
        if price0 <= 0:
          continue
        for target in dollar_figs:
          if stream0 > 0 and abs(stream0 - target) / target <= 0.05:
            continue  # already coherent; nothing to land
          for count in count_figs:
            if abs(count * price0 * util0 - target) / target <= 0.02:
              p_after["units_per_period_capacity"] = count / periods0
              name0 = str(p_after.get("product_name") or p_after.get("unit_name") or "that side").strip()
              new_stream = price0 * (count / periods0) * periods0 * util0
              return ops_after, {
                "reverted": [],
                "confirm": None,
                "stream_note": (
                  f" Your {name0} side now models at about "
                  f"{_format_currency(new_stream)} a year against the "
                  f"{_format_currency(target)} you reported."
                ),
              }
    return ops_after, None
  # Stream arithmetic for the (single) corrected product - the client
  # thinks in dollars, so the ack must too.
  note: Dict[str, Any] = {"reverted": reverted, "stream_note": "", "confirm": None}
  changed = changed_products[0]
  p = changed["after"]
  price = _safe_float(p.get("unit_price")) or 0.0
  cap = _safe_float(p.get("units_per_period_capacity")) or 0.0
  periods = _safe_float(p.get("operating_periods_per_year")) or 12.0
  util = _safe_float(p.get("utilization_rate"))
  util = util if util and 0.0 < util <= 1.0 else 1.0
  stream = price * cap * periods * util
  if stream <= 0:
    return ops_after, note
  name = str(p.get("product_name") or p.get("unit_name") or "that side").strip()
  stated_candidates = [f for f in figures if f >= 1000.0]

  def _find_anchor() -> Optional[float]:
    for f in stated_candidates:
      if abs(stream - f) / f <= 0.05:
        return f
    return None

  anchor = _find_anchor()
  if anchor is None and price > 0 and util > 0 and periods > 0:
    # (e) DETERMINISTIC CAPACITY LANDING (CW-012 blocker): the router
    # MODEL rounds fractional capacity - 2.5/period became 2 across
    # three differently-worded asks; there is no code coercion, so
    # prompt-nudging cannot fix it. When the client's own numbers
    # cohere - a stated annual count F times price times the KEPT
    # utilization matches a stated dollar figure D - the capacity
    # arithmetic runs HERE: capacity = F / periods. GPT interprets
    # language; Python does the math.
    count_figs = [
      f for f in figures if 1.0 < f <= 2000.0 and abs(f - round(f)) < 1e-6
    ]
    for target in stated_candidates:
      hit = False
      for count in count_figs:
        if abs(count * price * util - target) / target <= 0.02:
          p["units_per_period_capacity"] = count / periods
          cap = count / periods
          stream = price * cap * periods * util
          anchor = target
          hit = True
          break
      if hit:
        break
  if anchor is not None:
    note["stream_note"] = (
      f" Your {name} side now models at about {_format_currency(stream)} a year "
      f"against the {_format_currency(anchor)} you reported."
    )
  else:
    miss = None
    for f in stated_candidates:
      # Only treat a figure as the intended stream target when it is in
      # the stream's neighborhood (within 40%) - revenue/other figures
      # in the same message must not masquerade as the stream.
      if abs(stream - f) / f <= 0.40:
        miss = f
        break
    if miss is not None and price * cap * periods > 0:
      util_needed = miss / (price * cap * periods)
      if 0.0 < util_needed <= 1.0:
        # RARE branch by construction: the client's own figures disagree
        # beyond tolerance - ask, never silently pick a winner. (c): the
        # question travels with a pending frame so the client's "yes"
        # (or a restated percent) LANDS the proposed value structurally
        # - CW-012's "Yes - 75%" changed nothing because nothing routed
        # the answer.
        note["confirm"] = (
          f" One check: with those numbers the {name} side models at about "
          f"{_format_currency(stream)} a year, but you mentioned "
          f"{_format_currency(miss)} - to hit that I'd put utilization at "
          f"about {util_needed:.0%}. Does that look right?"
        )
        note["pending_frame"] = {
          "lob_index": int(changed["lob_index"]),
          "product_index": int(changed["product_index"]),
          "field": "utilization_rate",
          "proposed": float(util_needed),
        }
      else:
        note["stream_note"] = (
          f" Your {name} side now models at about {_format_currency(stream)} a year."
        )
    else:
      note["stream_note"] = (
        f" Your {name} side now models at about {_format_currency(stream)} a year."
      )
  # (d) figure-coverage backstop: a large stated figure that ended up
  # matched by NOTHING - no kept lever value, no stream, no anchor - is
  # surfaced instead of silently dropped (CW-012: "you took the 8,000,
  # you kept the old capacity" - the 30 and the 180,000 both vanished).
  if note.get("confirm") is None:
    used = {anchor} if anchor is not None else set()
    covered_vals = [price, cap, cap * periods, util * 100.0, periods, stream]
    uncovered: List[float] = []
    for f in figures:
      if f < 2.0 or (f in used if used else False):
        continue
      if f < 1000.0 and abs(f - round(f)) > 1e-6:
        continue
      if any(cv > 0 and abs(f - cv) / max(cv, 1e-9) <= 0.02 for cv in covered_vals):
        continue
      if f >= 1000.0 and any(
        abs(f - sc) / sc <= 0.02 for sc in stated_candidates if sc == (anchor or 0)
      ):
        continue
      if f >= 1000.0 or (2.0 <= f <= 2000.0 and abs(f - round(f)) < 1e-6):
        if f >= 1000.0 and anchor is not None and abs(f - anchor) / anchor <= 0.02:
          continue
        uncovered.append(f)
    # Figures that legitimately describe OTHER parts of the business
    # (revenue, other streams) will appear here too - only flag when the
    # correction's own arithmetic left something visibly unused, and cap
    # the list to avoid interrogation.
    if uncovered and len(uncovered) <= 2 and note.get("stream_note") and anchor is None:
      vals = " and ".join(
        _format_currency(v) if v >= 1000.0 else f"{v:g}" for v in uncovered[:2]
      )
      note["stream_note"] += (
        f" (I didn't end up using {vals} - if that should change the model, tell me where.)"
      )
  return ops_after, note


def _basis_clarify_closed_question(pending: Dict[str, Any]) -> str:
  """Deterministic, frame-declared statement of WHAT must be asked. The
  natural phrasing (HOW) comes from the recovery-phrasing helper; this text
  is the always-safe fallback."""
  kind = str(pending.get("kind") or "").strip()
  if kind == "driver_price":
    unit = str(pending.get("unit_name") or pending.get("product_name") or "unit").strip()
    stated = float(pending.get("stated_value") or 0.0)
    implied = float(pending.get("implied_revenue") or 0.0)
    revenue = float(pending.get("stated_revenue") or 0.0)
    asked = str(pending.get("asked_basis") or "").strip()
    candidate = str(pending.get("candidate_basis") or "").strip()
    per_asked = {"weekly": "per week", "monthly": "per month", "annual": "per year"}.get(asked, asked)
    per_candidate = {"weekly": "per week", "monthly": "per month", "annual": "per year"}.get(candidate, candidate)
    # Model A: the app does the arithmetic and PROPOSES its inference for
    # the client to confirm - it never asks the client to compute or
    # restate in a format. The router interprets whatever they answer.
    return (
      f"Taken {per_asked}, the {unit} figure would put revenue around "
      f"{_format_currency(implied)} a year, but you mentioned about "
      f"{_format_currency(revenue)} - did you mean {_format_currency(stated)} "
      f"{per_candidate} rather than {per_asked}?"
    )
  if kind == "driver_price_scope":
    unit = str(pending.get("unit_name") or pending.get("product_name") or "unit").strip()
    stated = float(pending.get("stated_value") or 0.0)
    implied = float(pending.get("implied_revenue") or 0.0)
    revenue = float(pending.get("stated_revenue") or 0.0)
    asked = str(pending.get("asked_basis") or "monthly").strip()
    per_asked = {"weekly": "per week", "monthly": "per month", "annual": "per year"}.get(asked, asked)
    return (
      f"Taken {per_asked}, the {unit} figure would put revenue around "
      f"{_format_currency(implied)} a year, but you mentioned about "
      f"{_format_currency(revenue)} - is the {_format_currency(stated)} the total "
      f"for a typical {unit} rather than {per_asked}? If so, roughly what does a "
      f"typical {unit} bring in {per_asked}?"
    )
  if kind == "percent_vs_dollar":
    raw = float(pending.get("stated_value") or 0.0)
    as_percent = float(pending.get("percent_reading_dollars") or 0.0)
    as_dollars = float(pending.get("dollar_reading") or 0.0)
    return (
      f"Quick check on that figure: read as a percent of revenue it comes to about "
      f"{_format_currency(as_percent)} a year, but you might have meant about "
      f"{_format_currency(as_dollars)} - which did you mean?"
    )
  if kind == "stage_amount":
    stated = float(pending.get("stated_value") or 0.0)
    return (
      f"One quick check: is the {_format_currency(stated)} per month, or for "
      f"the whole year?"
    )
  return "Could you confirm whether that figure is per week, per month, or per year?"


def _build_basis_clarify_message(pending: Dict[str, Any], *, user_message: str = "") -> str:
  closed = _basis_clarify_closed_question(pending)
  # Model A: the app SHOWS ITS MATH. The phrasing may be natural but every
  # dollar figure in the closed question must survive - the client confirms
  # the app's arithmetic, so they have to see it.
  task = (
    f"{closed} (Keep every dollar figure from this question in your phrasing - "
    f"the client needs to see the arithmetic they are confirming.)"
  )
  try:
    from client_intake_and_finmo.recovery_phrasing import naturalize_recovery  # type: ignore

    return naturalize_recovery(closed_question=task, user_message=user_message, fallback=closed)
  except Exception:
    return closed


def _apply_basis_clarify_resolution(
  *,
  conn,
  draft_id: str,
  resolution: Dict[str, Any],
  pending: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
  """Land the client's basis answer at the SOURCE. driver_price corrections
  write the converted price into ops_json.lob_models (the true driver
  authority — a financials_year1-only write is reverted by the drivers
  conflict guard on the next rebuild) and reassemble year1 from it.
  stage_amount corrections convert the financials field in place. Returns
  (financials_json, financials_year1_json, acknowledgement)."""
  next_financials = dict(financials_json or {})
  next_year1 = dict(financials_year1_json or {})
  meant = str(resolution.get("basis") or "").strip().lower()
  restated = _safe_float(resolution.get("amount"))
  kind = str(pending.get("kind") or "").strip()
  acknowledgement = ""

  confirmed_original = (
    meant in ("as_stated", "keep", "keep_as_stated")
    or meant == str(pending.get("asked_basis") or "")
  )
  if kind == "percent_vs_dollar":
    field_name = str(pending.get("field") or "").strip()
    if meant in ("dollars", "dollar", "amount") or (restated is not None and meant not in ("percent",)):
      dollars = restated if restated is not None else _safe_float(pending.get("dollar_reading"))
      revenue = _safe_float(pending.get("stated_revenue")) or 0.0
      if field_name and dollars is not None:
        total_field = field_name.replace("_percent_of_revenue", "_total_year1")
        next_financials[total_field] = float(dollars)
        if revenue > 0:
          next_financials[field_name] = float(dollars) / revenue
        if total_field == "marketing_total_year1":
          next_financials = _sync_marketing_field_family(
            financials_json=next_financials,
            financials_year1_json=next_year1,
            marketing_model_json={},
          )
        acknowledgement = (
          f"Thanks — {_format_currency(float(dollars))} a year it is."
        )
    else:
      recorded = str(pending.get("recorded") or "percent").strip()
      if recorded == "dollars" and meant == "percent":
        # Reverse direction (CW-009): the router recorded DOLLARS; the
        # client says they meant a percent - write the ratio and re-derive
        # the total from it.
        pct = _safe_float(pending.get("stated_value"))
        revenue = _safe_float(pending.get("stated_revenue")) or 0.0
        if field_name and pct is not None and revenue > 0:
          total_field = field_name.replace("_percent_of_revenue", "_total_year1")
          next_financials[field_name] = float(pct)
          next_financials[total_field] = float(pct) * revenue
          if total_field == "marketing_total_year1":
            next_financials = _sync_marketing_field_family(
              financials_json=next_financials,
              financials_year1_json=next_year1,
              marketing_model_json={},
            )
          acknowledgement = (
            f"Got it — {pct * 100:.0f}% of revenue, about "
            f"{_format_currency(float(pct) * revenue)} a year."
          )
        else:
          acknowledgement = "Got it — I'll read that as a percent of revenue."
      elif recorded == "dollars":
        # as-stated: the recorded dollar total stands.
        kept = _safe_float(pending.get("dollar_reading")) or 0.0
        acknowledgement = (
          f"Got it — I'll keep that as {_format_currency(kept)} a year."
        )
      else:
        # percent (or as-stated): the recorded ratio stands.
        acknowledgement = "Got it — I'll read that as a percent of revenue."
    next_financials.pop("_basis_clarify_pending", None)
    next_financials.pop("_basis_clarify_resolution", None)
    return next_financials, next_year1, acknowledgement
  if confirmed_original and restated is None:
    # The client confirmed the original figure and basis. The conflict (if
    # any) stands as the client's own account; reconciliation resumes.
    acknowledgement = "Got it — I'll keep that figure exactly as you gave it."
  elif kind in ("driver_price", "driver_price_scope") and (
    meant in _BASIS_PERIODS_PER_YEAR
    or (confirmed_original and restated is not None)
    or (kind == "driver_price_scope" and restated is not None)
  ):
    if confirmed_original and meant not in _BASIS_PERIODS_PER_YEAR:
      meant = str(pending.get("asked_basis") or "").strip().lower()
    stored_basis = str(pending.get("asked_basis") or "").strip().lower()
    stored_periods = _BASIS_PERIODS_PER_YEAR.get(stored_basis)
    meant_periods = _BASIS_PERIODS_PER_YEAR.get(meant)
    stated_value = restated if restated is not None else _safe_float(pending.get("stated_value"))
    if stored_periods and meant_periods and stated_value is not None:
      converted = float(stated_value) * (meant_periods / stored_periods)
      ops_json = dict((shared_context or {}).get("operating_model") or {})
      target_lob = str(pending.get("lob_name") or "").strip().lower()
      target_product = str(pending.get("product_name") or "").strip().lower()
      lob_models = copy.deepcopy(ops_json.get("lob_models") or [])
      landed = False
      for lob in lob_models:
        if not isinstance(lob, dict):
          continue
        if target_lob and str(lob.get("lob_name") or lob.get("name") or "").strip().lower() != target_lob:
          continue
        for product in lob.get("products") or []:
          if not isinstance(product, dict):
            continue
          name = str(product.get("product_name") or product.get("name") or "").strip().lower()
          if target_product and name != target_product:
            continue
          product["unit_price"] = converted
          landed = True
      if landed:
        ops_json = _apply_model_ops_patch(ops_json, {"lob_models": lob_models})
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[],
          operating_model_json=ops_json,
          active_focus="financials",
          business_facts=business_facts,
        )
        next_shared = dict(shared_context or {})
        next_shared["operating_model"] = ops_json
        shared_context.clear()
        shared_context.update(next_shared)
        try:
          from financials_year1 import assemble_financials_year1  # type: ignore
        except Exception:
          from client_intake_and_finmo.financials_year1 import assemble_financials_year1  # type: ignore
        next_year1 = assemble_financials_year1(next_shared, None)
        per_meant = {"weekly": "a week", "monthly": "a month", "annual": "a year"}.get(meant, meant)
        acknowledgement = (
          f"Thanks — I've recorded that as {_format_currency(float(stated_value))} "
          f"{per_meant} and updated the revenue math to match."
        )
  elif kind == "stage_amount" and meant in _BASIS_PERIODS_PER_YEAR:
    field_name = str(pending.get("field") or "").strip()
    stored_periods = _BASIS_PERIODS_PER_YEAR.get(str(pending.get("asked_basis") or "annual"))
    meant_periods = _BASIS_PERIODS_PER_YEAR.get(meant)
    stated_value = restated if restated is not None else _safe_float(pending.get("stated_value"))
    if field_name and stored_periods and meant_periods and stated_value is not None:
      converted = float(stated_value) * (meant_periods / stored_periods)
      next_financials[field_name] = converted
      if field_name == "marketing_total_year1":
        next_financials = _sync_marketing_field_family(
          financials_json=next_financials,
          financials_year1_json=next_year1,
          marketing_model_json={},
        )
      per_meant = {"weekly": "a week", "monthly": "a month", "annual": "a year"}.get(meant, meant)
      acknowledgement = (
        f"Thanks — {_format_currency(float(stated_value))} {per_meant} it is; "
        f"I've recorded the annual figure as {_format_currency(converted)}."
      )

  next_financials.pop("_basis_clarify_pending", None)
  next_financials.pop("_basis_clarify_resolution", None)
  return next_financials, next_year1, acknowledgement


_FINANCIALS_FIELD_LABELS = {
  "ar_balance": "accounts receivable",
  "ap_balance": "operating payables",
  "cash_on_hand": "cash on hand",
  "other_operating_expense": "other operating costs",
  "owner_compensation": "owner compensation",
  "monthly_rent_expense": "rent",
  "total_debt_outstanding": "outstanding debt",
  "current_num_employees": "employee count",
  "inventory_balance": "inventory",
}


def _unapplied_fields_note(dropped: List[str]) -> str:
  """Factual, deterministic note appended when a router patch mentioned
  fields that did not apply (issue #23 say-do rule: the client hears what
  was NOT recorded, never a false confirmation). With corrections to
  complete stages now admitted, the residue here is future-stage fields —
  their stages will ask, so 'we'll get to that' is literally true."""
  labels = [
    _FINANCIALS_FIELD_LABELS.get(f, f.replace("_", " ")) for f in dropped if f
  ]
  if not labels:
    return ""
  if len(labels) == 1:
    listed = labels[0]
  else:
    listed = ", ".join(labels[:-1]) + " and " + labels[-1]
  return f"(One note: I haven't recorded {listed} yet — we'll get to that in a moment.)"


def _natural_recovery(closed_question: str, *, user_message: str = "", fallback: str = "") -> str:
  """Bluntness-class cure (client-facing fallbacks only): frame-declared
  WHAT via closed_question; natural GPT phrasing for HOW; deterministic
  fallback always intact."""
  try:
    from client_intake_and_finmo.recovery_phrasing import naturalize_recovery  # type: ignore
    return naturalize_recovery(
      closed_question=closed_question,
      user_message=user_message,
      fallback=fallback or closed_question,
    )
  except Exception:
    return fallback or closed_question


def _natural_continue(focus: str = "") -> str:
  try:
    from client_intake_and_finmo.recovery_phrasing import continuation_nudge  # type: ignore
    return continuation_nudge(focus=focus)
  except Exception:
    return "Continue."


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
  return f"Got it. I’ll treat {option['label'].lower()} as the preferred cash posture."


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
  report: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  if not isinstance(patch, dict) or not patch:
    return None
  stage_name = str(active_stage or "").strip()
  active_targets = set(_financials_stage_spec(stage_name).get("patch_targets") or ())
  if not active_targets:
    return None
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  # Basis-clarify resolution rides outside the stage-field whitelist: it
  # answers the app's own pending basis question, not a stage question.
  # Stash it for _advance_persisted_financials_stage to land at the source.
  _resolution_raw = patch.get("basis_clarify_resolution")
  if _resolution_raw is None:
    _resolution_raw = patch.get("financials.basis_clarify_resolution")
  _resolution_landed = False
  if isinstance(_resolution_raw, dict) and isinstance(
    next_financials.get("_basis_clarify_pending"), dict
  ):
    next_financials["_basis_clarify_resolution"] = {
      "basis": str(_resolution_raw.get("basis") or "").strip().lower(),
      "amount": _safe_float(_resolution_raw.get("amount")),
    }
    _resolution_landed = True
  # CORRECTIONS ARE ADMITTED (issue #23): the narrowing's job is to stop
  # answers landing in FUTURE fields (misroutes), never to reject a
  # correction to a field the client already deliberately captured. A
  # three-field correction (cash/AR/AP in one message) was narrowed to
  # the active stage's single field while the router's confirmation
  # promised all three — the submitted model shipped with cash and AR
  # silently zeroed. A field is correctable when its owning stage is
  # already COMPLETE.
  correctable: set[str] = set()
  for _st in _FINANCIALS_STAGE_ORDER:
    if _st == stage_name:
      continue
    try:
      if _financials_stage_complete(_st, next_financials):
        correctable.update(_financials_stage_spec(_st).get("patch_targets") or ())
    except Exception:
      continue
  # VOLUNTEERED SIBLINGS ARE ADMITTED (issue #33): a client answering the
  # total-debt question with "we owe 180k - interest runs 9,200 and
  # principal 15,000" names all three concepts; narrowing to the active
  # field dropped the volunteered pair and the flow re-asked questions
  # the client had already answered. Within a same-topic cluster the
  # router only writes fields it explicitly identified (a bare number
  # still lands on the asked field), so sibling fields land and their
  # stages complete - never re-asked. Future-field protection is
  # unchanged outside the cluster.
  _VOLUNTEER_CLUSTERS = (
    {
      "total_debt_outstanding",
      "other_monthly_debt_payments",
      "annual_interest_payment",
      "annual_principal_payment",
    },
    {"cash_on_hand", "ar_balance", "ap_balance", "inventory_balance"},
  )
  volunteered: set[str] = set()
  for _cluster in _VOLUNTEER_CLUSTERS:
    if active_targets & _cluster:
      volunteered |= _cluster
  allowed_fields = active_targets | correctable | volunteered
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
      # No basis second-guessing here: the router is the ONLY basis
      # normalizer (field_basis registry names the stored basis in the
      # router frame). The old apply-layer x12 heuristic believed this
      # monthly field was annual and turned a correct $10,000/mo into
      # $120,000/mo (Harborline false park, run CW-001).
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
    if field_name == "funding_preference":
      option = _funding_preference_option(raw_value)
      if option is None:
        continue
      next_financials[field_name] = option["value"]
      touched.add(field_name)
      continue
    if field_name == "funding_split_debt_share":
      share = _funding_split_share_value(raw_value)
      if share is None:
        continue
      next_financials[field_name] = float(share)
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
    # (Former marketing x12 shim removed - same class as the owner_comp
    # shim above: the router owns basis normalization, declared per field
    # by the field_basis registry.)
    next_financials[field_name] = float(numeric)
    touched.add(field_name)
  # Say-do accounting (issue #23): the caller derives the confirmation
  # from what was ACTUALLY applied. Anything in the patch that did not
  # land is reported so the client hears it — never a false "recorded".
  if isinstance(report, dict):
    _requested = set()
    for _rk in patch.keys():
      _f = str(_rk or "").strip()
      if _f.startswith("financials."):
        _f = _f.split(".", 1)[1].strip()
      if _f:
        _requested.add(_f)
    report["applied"] = sorted(touched)
    report["dropped"] = sorted((_requested - touched) - {"basis_clarify_resolution"})
  if not touched and not _resolution_landed:
    return None
  if stage_name == "revenue_intro" and "current_revenue" in touched:
    next_financials["_financials_revenue_intro_done"] = True
  if stage_name == "marketing" and (
    "marketing_total_year1" in touched or "marketing_percent_of_revenue" in touched
  ):
    next_financials["_financials_marketing_stage_done"] = True
  # Unmarked-basis capture checks (issues #24/#25): stamp a pending clarify
  # when the just-landed answer is implausible against what the client
  # already said. Never re-stamp over an in-flight clarify.
  if not isinstance(next_financials.get("_basis_clarify_pending"), dict):
    # Layer 1: the UNIVERSAL gate - every touched registry field consults
    # one shared signal (basis_gate.gate_numeric); the old per-site
    # detector wiring is subsumed as gate internals keyed by field class.
    try:
      from client_intake_and_finmo.basis_gate import gate_numeric  # type: ignore

      _gate_detectors = {
        "revenue_driver": _detect_revenue_driver_basis_conflict,
        "stage_amount": _detect_stage_amount_basis_conflict,
        "percent_vs_dollar": _detect_percent_vs_dollar_conflict,
        "dollar_vs_percent": _detect_dollar_vs_percent_conflict,
      }
      _gate_ctx = {
        "financials_json": next_financials,
        "financials_year1_json": financials_year1_json or {},
      }
      for _gf in sorted(touched):
        if _gf.endswith("_percent_of_revenue"):
          _twin = _gf.replace("_percent_of_revenue", "_total_year1")
          if _twin in touched or "current_cogs" in touched:
            # Twin-skip, refined (CW-010): both twins present usually
            # means the percent was re-derived from an authoritative
            # dollar total — but when the router READ an unmarked bare
            # figure as a percent it writes both twins itself, and the
            # blanket skip suppressed the only detector that could catch
            # the misread ("about twelve" -> 12% -> $127,200 for a $12k
            # intent). Run the forward check anyway IFF the raw figure
            # (pct x 100) appears verbatim in the client's words — the
            # fingerprint that the percent IS the router's direct
            # reading. Dollar-stated answers ("21,600 for the year" ->
            # pct 2.06, absent from the message) never fire.
            _pv = _safe_float(next_financials.get(_gf))
            if _pv and _pv > 0:
              _raw_n = _pv * 100.0
              if any(
                abs(c - _raw_n) < 0.51
                for c in _percent_shaped_figures(user_message)
              ):
                _pending_tw = _detect_percent_vs_dollar_conflict(
                  field_name=_gf,
                  percent_value=float(_pv),
                  financials_json=next_financials,
                  user_message=user_message,
                )
                if _pending_tw:
                  next_financials["_basis_clarify_pending"] = _pending_tw
                  break
            continue  # total is authoritative; percent was re-derived
        _gv = _safe_float(next_financials.get(_gf))
        if _gv is None:
          continue
        _verdict = gate_numeric(
          field=f"financials.{_gf}", value=float(_gv), stated_basis=None,
          user_message=user_message, context=_gate_ctx, detectors=_gate_detectors,
        )
        if _verdict.get("verdict") == "clarify" and _verdict.get("pending"):
          next_financials["_basis_clarify_pending"] = _verdict["pending"]
          break
    except Exception:
      pass
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
  # Derived-percent discipline (CW-007 class): when a patch carries BOTH a
  # total and its percent, the total wins and the percent is re-derived -
  # the GPT router can convert the total's basis correctly while computing
  # the percent from the client's raw (differently-based) figure.
  if "marketing_total_year1" in touched and "marketing_percent_of_revenue" in touched:
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    if revenue_year1 and revenue_year1 > 0:
      next_financials["marketing_percent_of_revenue"] = (
        float(next_financials.get("marketing_total_year1") or 0.0) / revenue_year1
      )
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
    patched = apply_revenue_driver_patch(next_year1, {"product_overrides": product_overrides})
    # Provenance stamp: the drivers-conflict guard compares capacities
    # against the raw ops rebuild and used to read this deliberate rescale
    # as staleness, discarding it every turn (the rescale was never
    # durable; the phantom ops basis stayed authoritative). The stamp lets
    # the guard recognize capacity diffs that are exactly this factor.
    if isinstance(patched, dict):
      patched["_rescale_provenance"] = {
        "source_total": float(current_total),
        "target_total": float(target_total),
        "factor": float(factor),
      }
    return patched
  except Exception:
    return next_year1


def _sync_financials_consult_persistence_state(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  # current_revenue is only an authoritative rescale target once the client has
  # actually established the revenue baseline (revenue_intro answered). Before
  # that it is a derived echo that may predate later-entered lines of business;
  # rescaling to it would shrink real driver capacities to fit a stale total.
  # While a basis clarify is pending, the numbers are in dispute: no silent
  # capacity rescale (it would repair the wrong degree of freedom — the
  # Bridgeburn crush turned the client's stated 60 accounts into 14.9) and
  # the client's stated current_revenue stays authoritative.
  basis_clarify_pending = isinstance(next_financials.get("_basis_clarify_pending"), dict)
  if bool(next_financials.get("_financials_revenue_intro_done")) and not basis_clarify_pending:
    next_year1 = _rescale_financials_year1_to_current_revenue(
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
    )
  else:
    next_year1 = dict(financials_year1_json or {})

  revenue_year1 = _safe_float(next_year1.get("company_revenue_total_year1")) or 0.0
  if revenue_year1 > 0 and not basis_clarify_pending:
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

  # other_operating_expense is captured MONTHLY (the question asks for a typical
  # month); post-intake consumers want the ANNUAL absolute and already prefer
  # other_opex_absolute. Derive it here so the annual field always exists and the
  # monthly figure is never mistaken for an annual one downstream.
  monthly_other_opex = _safe_float(next_financials.get("other_operating_expense"))
  if monthly_other_opex is not None and monthly_other_opex >= 0:
    next_financials["other_opex_absolute"] = float(monthly_other_opex) * 12.0

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
  next_financials = _maybe_autocomplete_revenue_intro(next_financials, shared_context)
  next_financials = _maybe_autocomplete_payroll_stage(next_financials, shared_context)
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
      financials_json=fin_json,
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
  _pending_clarify_live = next_financials.get("_basis_clarify_pending")
  if not str(user_message or "").strip():
    if isinstance(_pending_clarify_live, dict) and _pending_clarify_live:
      return {
        "assistant_message": _build_basis_clarify_message(_pending_clarify_live),
        "finalize_ready": False,
      }, next_financials
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

  if isinstance(_pending_clarify_live, dict) and _pending_clarify_live:
    # The app's basis question is the open thread: only a resolution moves
    # the flow forward. A confirm_proceed here would author stage defaults
    # on numbers currently in dispute; any non-answer gets one natural
    # re-ask (never a trap — every phrasing routes through the resolution
    # rule, and "as stated" is always available).
    _res_probe = (patch or {}).get("basis_clarify_resolution")
    if _res_probe is None:
      _res_probe = (patch or {}).get("financials.basis_clarify_resolution")
    if not isinstance(_res_probe, dict):
      return {
        "assistant_message": _build_basis_clarify_message(
          _pending_clarify_live, user_message=user_message,
        ),
        "finalize_ready": False,
      }, next_financials

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
    _patch_report: Dict[str, Any] = {}
    normalized_patch = _normalize_financials_router_patch(
      patch=patch,
      active_stage=active_stage,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      last_assistant=last_assistant,
      user_message=user_message,
      report=_patch_report,
    )
    if isinstance(normalized_patch, dict) and normalized_patch:
      # Layer 2: the write-derived acknowledgment (built from the APPLIED
      # patch) outranks the router's free prose - prose can quote a number
      # the whitelist dropped; the applied-values ack cannot.
      acknowledgement = _build_financials_stage_acknowledgement_first(assistant_message,
        stage_name=active_stage,
        financials_json=normalized_patch,
      )
      _dropped = list(_patch_report.get("dropped") or [])
      if _dropped:
        _note = _unapplied_fields_note(_dropped)
        if _note:
          acknowledgement = f"{acknowledgement} {_note}".strip()
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
          # Layer 2: the write-derived acknowledgment (built from the APPLIED
          # patch) outranks the router's free prose.
          acknowledgement = _build_financials_stage_acknowledgement_first(
            assistant_message,
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
      # Layer 2: the write-derived acknowledgment (built from the APPLIED
      # patch) outranks the router's free prose - prose can quote a number
      # the whitelist dropped; the applied-values ack cannot.
      acknowledgement = _build_financials_stage_acknowledgement_first(assistant_message,
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
    "assistant_message": _natural_recovery(
      _build_financials_stage_clarifier(active_stage),
      user_message=str(user_message or ""),
      fallback=_build_financials_stage_clarifier(active_stage),
    ),
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

  # A capacity diff that is exactly the stated-revenue rescale factor is
  # DELIBERATE reconciliation, not staleness. Without this, the guard
  # discarded the rescaled year1 every turn and the raw ops drivers stayed
  # permanently authoritative (post-intake consumed the phantom basis).
  rescale_factor: Optional[float] = None
  provenance = existing_year1.get("_rescale_provenance")
  if isinstance(provenance, dict):
    factor = _num(provenance.get("factor"))
    if factor and factor > 0:
      rescale_factor = float(factor)

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
      if rescale_factor is None:
        return True
      expected = base_capacity * rescale_factor
      tolerance = max(0.01, abs(expected) * 0.01)
      if abs(existing_capacity - expected) > tolerance:
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
      "rest_of_team_payroll_year1",
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
      "Review this draft (key people narrative + suggested roles with wages and timing) and tell me any changes."
    )
  elif has_people:
    parts.append("Review this draft (key people narrative) and tell me any changes.")
  elif has_roles:
    parts.append("Review these suggested roles (with wages and timing) and tell me any changes.")

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
  conversation_messages: Optional[List[Dict[str, str]]] = None,
) -> str:
  key = _openai_key()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  _system_lines = [
    "You are a senior business consultant drafting a WORKING HYPOTHESIS of a",
    "company's competitive advantage for the client to react to.",
    "",
    "This is NOT marketing language, and it is NOT a settled fact - the client",
    "is the authority on what sets their business apart; your draft exists to",
    "be corrected or confirmed.",
    "",
    "Context: you are given the operating model (business type and stage, unit",
    "definition and pricing, capacity driver, fulfillment and delivery model,",
    "geography, customer type) and the client's own recent words from the",
    "conversation.",
    "",
    "Your task: draft ONE concise competitive-advantage hypothesis that explains:",
    "1) What this business plausibly does differently from typical competitors",
    "2) Why that difference exists operationally (process, structure, constraints, choices)",
    "3) Why it matters economically or experientially to the customer",
    "",
    "Hard rules:",
    "- Ground the hypothesis in what the client actually said whenever their words",
    "  touch on strengths, specialization, relationships, or how they win work -",
    "  prefer their own account over inference from the operating model.",
    "- Do NOT use generic phrases (high quality, great service, customer-focused,",
    "  fast, personalized) unless you explain how they are structurally enabled.",
    "- Do NOT describe multiple advantages - pick the single most defensible one.",
    "- Do NOT restate the business description.",
    "- Do NOT assert claims the facts cannot support (e.g., how hard the advantage",
    "  is to replicate) - if you infer something, frame it as a read, not a fact.",
    "- Tie the advantage to at least ONE concrete operational choice.",
    "- Keep it to 2-3 sentences total.",
    "",
    "Output only the hypothesis text - the app adds its own framing and",
    "confirmation question.",
  ]
  system = chr(10).join(_system_lines)
  ops_payload = dict(ops_json or {})
  ops_payload["business_type"] = (ops_json or {}).get("business_type")
  ops_payload["business_naics_6"] = (ops_json or {}).get("business_naics_6")
  recent_client_words: List[str] = []
  for _m in (conversation_messages or [])[-24:]:
    if isinstance(_m, dict) and str(_m.get("role") or "").strip() == "user":
      _txt = str(_m.get("content") or "").strip()
      if _txt:
        recent_client_words.append(_txt[:600])
  context_payload = {
    "confirmed_restatement": confirmed_restatement,
    "ops": ops_payload,
    "client_recent_messages": recent_client_words[-8:],
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

  # Phase 9 P3.32 K11 L-4 â€” open the handler trace run at the TRUE entry,
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
    # Module 5 Task 5.1 â€” GPT call DELETED. The deterministic NAICS-cascade
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

  # Phase 9 P3.32 K11 L-4 â€” stamp the real planning_run_id now that the
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
      # Phase 9 P3.10 Commit 5 Part B â€” email-on-failure + FAILED
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
    # â•â•â• THE RESTRUCTURE STAGE (additive; fires ONLY on NON-VIABLE) â•â•â•
    # The full existing process ran unchanged above. A VIABLE verdict
    # never enters this block â€” nothing changes for viable businesses.
    # On NON-VIABLE, the EXECUTIVE redesigns the whole business (design
    # seat: headcount, space, mix, pricing, phasing â€” bounded ONLY by
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
          # the currently-planned Q11 â€” the mix picture the executive
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

        # â•â•â• RESTRUCTURE v2: bounds â†’ whole-P&L search â†’ review â†’ real run â•â•â•
        # 1. The EXECUTIVE authors the four reality constraints as BOUNDS.
        # 2. The SOLVER searches every configuration inside them (fast
        #    evaluator = the pipeline's own math + the gate's own checks).
        # 3. The EXECUTIVE reviews the found design (real business? may
        #    tighten caps once â€” the solver re-searches inside them).
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
        # THE JOINT SOLVE â€” GPT authored the bounds and target OUTSIDE
        # the loop; numeric_solver.solve_review_plan (the existing SciPy
        # joint optimizer) drives ALL levers simultaneously to the
        # viability target inside them. GPT reviews the solved result
        # OUTSIDE the loop; each rejection tightens bounds for a
        # re-solve (the solve is seconds). Exactly ONE real pipeline
        # run, only after approval.
        _rs_max_rounds = 4
        for _rs_i in range(1, _rs_max_rounds + 1):
          if not (_rs_bounds and _rs_bounds.get("feasible_region_exists")):
            # The executive concluded no REAL region exists â€” the
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
            # refine-back walked toward as-stated) â€” audit signal for how
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
            # spent â€” the honest terminal.
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
          # run id â€” the resolved row then reads NULLs and three purely
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
        # unshipped designs) â€” but the ATTEMPTED design the solver
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
        except Exception as _rs_wb_exc:  # noqa: BLE001 â€” artifact export must not kill the run
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
    except Exception as _rs_exc:  # noqa: BLE001 â€” the pre-restructure verdict stands
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

    # Phase 9 P3.20 Part 1 + Part 1b Concern 2 â€” post-run workbook
    # Model Status fail-fast. Differentiates environment failure (log
    # and continue) from genuine status failure (always re-raise, in
    # both test and production modes).
    #
    # Environment failures (no pywin32, no Excel COM, module import
    # broken) â†’ log warning, run continues. These are infrastructure
    # problems that shouldn't kill business runs.
    #
    # Status read successfully and != "OK" â†’ always raise. A
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
    # THE PRIMARY WORKBOOK IS THE RUN'S STORY. When restructure fired
    # and the verdict stayed non-passed, what happened this run IS the
    # restructure attempt â€” the multi-line design the solver evaluated
    # â€” so THAT file (clearly marked in its name) is the one delivered
    # and emailed. The reverted-original workbook stays on disk for the
    # record but is never the file the client receives. Computed OUTSIDE
    # the client-workbook guard so the attempt still ships even if the
    # client export failed.
    _primary_workbook_path = client_workbook_path
    try:
      if _rs_attempt_workbook_path and not bool(
        (diagnostic_payload or {}).get("acceptance_passed")
      ):
        _primary_workbook_path = _rs_attempt_workbook_path
    except Exception:
      _primary_workbook_path = client_workbook_path
    if _primary_workbook_path:
      try:
        import os as _delivery_os
        import shutil as _delivery_shutil
        _delivery_dir = (_delivery_os.getenv("FINMO_MODEL_DELIVERY_DIR") or "").strip()
        if _delivery_dir and _delivery_os.path.isfile(_primary_workbook_path):
          _delivery_os.makedirs(_delivery_dir, exist_ok=True)
          _delivery_dest = _delivery_os.path.join(
            _delivery_dir, _delivery_os.path.basename(_primary_workbook_path)
          )
          _delivery_shutil.copy2(_primary_workbook_path, _delivery_dest)
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
    if _primary_workbook_path:
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
        _rs_swapped = bool(
          _primary_workbook_path
          and _primary_workbook_path == _rs_attempt_workbook_path
          and _primary_workbook_path != client_workbook_path
        )
        subject = (
          f"[Planning Run] {biz_name} -- {verdict_label} ({score})"
          + (" -- RESTRUCTURE ATTEMPT ATTACHED" if _rs_swapped else "")
        )
        body = build_run_email_body(diagnostic_payload or {})
        if _rs_swapped:
          body = (
            "THE ATTACHED WORKBOOK IS THE RESTRUCTURE ATTEMPT â€” the "
            "multi-line design the solver evaluated this run (marked in "
            "the filename). No viable configuration existed inside the "
            "executive's reality bounds, so nothing shipped; this file "
            "shows what was tried and where it lands.\n\n" + body
          )
        email_outcome = send_workbook_alert(
          subject=subject,
          body=body,
          # ONE file: the run's primary workbook (the restructure
          # attempt when restructure fired and did not pass).
          attachment_paths=[_primary_workbook_path] if _primary_workbook_path else [],
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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• COHERENCE SECTION GLUE â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Intake does not close while the plan fails. The gate below runs at
# every financialsâ†’done completion site; the section brain lives in
# client_intake_and_finmo/intake_coherence (one shared evaluator with
# the Phase-0 backtest). State persists under financials_json["_coherence"].

def _coherence_naturalize(text: str) -> str:
  """GPT phrasing pass over a coherence turn (structured payload in,
  natural consultant voice out). The section wrapper verifies every
  dollar figure and the marker survive verbatim and falls back to the
  deterministic text otherwise â€” GPT can phrase, never invent."""
  key = _openai_key()
  if not key:
    return text
  system = (
    "Rewrite the consultant message below so it reads as one natural, warm, "
    "plain-English consulting turn (short paragraphs are fine).\n"
    "HARD RULES: keep every dollar figure, percentage, price, and option number "
    "EXACTLY as written; keep every option distinct and in the same order; keep "
    "the phrase 'work on paper'; never use the phrase 'Year 1'; do not add any "
    "new number, claim, or advice; NEVER use internal implementation vocabulary "
    "- no 'q11', 'Q11', 'eval', 'corner', 'solver', 'panel', 'model', 'band', "
    "'constraint set', or any mechanism-speak; the client hears only plain "
    "business language about their own quarter; do not mention these rules. "
    "Return only the rewritten message."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": text},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return text
  return str(_parse_responses_text(resp.json()) or "").strip() or text


def _coherence_gate(
  *,
  ops_json,
  people_json,
  market_json,
  marketing_model_json,
  financials_json,
  financials_year1_json,
  user_text="",
):
  """Wrapper over the section gate. Returns (turn_or_none,
  financials_json, completion_suffix).

  Failures propagate (doctrine: no silent degradation). A transient
  judgment failure (CoherenceJudgmentUnavailable / GPT transport)
  becomes the handler-level HOLD turn; anything else is a loud 500.
  The old "never strand a client at the finish line" swallow let a
  gate crash complete the intake with NO coherence check at all —
  exactly the class this workstream removes."""
  from client_intake_and_finmo.intake_coherence import section as _coh

  return _coh.gate_and_turn(
    ops_json=ops_json or {},
    people_json=people_json or {},
    market_json=market_json or {},
    marketing_model_json=marketing_model_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    naturalize=_coherence_naturalize,
    user_text=str(user_text or ""),
  )


_INTAKE_HOLD_MESSAGE = (
  "Give me a moment — I'm having trouble reaching my judgment engine right now. "
  "Everything you've shared is saved. Send that again in a moment, or come back "
  "shortly and we'll pick up exactly where you left off."
)

_TRANSIENT_JUDGMENT_ERROR_MARKERS = (
  "coherence_judgment_unavailable",
  "openai_request_failed",
  "gpt_response_lock_lookup_failed",
  "gpt_response_lock_save_failed",
)


def _transient_judgment_hold_message(exc: BaseException) -> Optional[str]:
  """Intake-time hold classification. Transient GPT/judgment-transport
  failures become an honest "give me a moment" turn (HTTP 200, turn
  persisted) — never a verdict, never a raw 500, never a silent
  constant. Anything else returns None and stays a loud server error."""
  if isinstance(exc, (TimeoutError, requests.exceptions.RequestException)):
    return _INTAKE_HOLD_MESSAGE
  text = str(exc or "")
  if any(marker in text for marker in _TRANSIENT_JUDGMENT_ERROR_MARKERS):
    return _INTAKE_HOLD_MESSAGE
  return None


def _coherence_blocked_response(
  *,
  conn,
  draft_id,
  client_id,
  user_msg,
  assistant_message: str,
  financials_json,
  business_facts,
):
  """Persist a coherence turn (completion blocked) and build the
  standard turn response. active_focus stays financials â€” the section
  is a stop inside the finish line, not a new stepper section."""
  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[user_msg, {"role": "assistant", "content": assistant_message}],
    financials_json=financials_json,
    active_focus="financials",
    business_facts=business_facts,
  )
  return jsonify(
    {
      "status": "ok",
      "draft_id": str(draft_id).strip(),
      "client_id": client_id,
      "active_focus": "financials",
      "awaiting_confirmation": True,
      "done": False,
      "action": "coherence",
      "assistant_message": assistant_message,
    }
  )


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
  client_id = ""
  active_focus_current = ""
  try:
    consult = get_draft(conn, draft_id=str(draft_id).strip())
    client_id = str(consult.get("client_id") or "").strip()
    active_focus_current = str(consult.get("active_focus") or "").strip()
    draft_status = str(consult.get("status") or "").strip().lower()
    if draft_status == "submitted":
      return (
        jsonify({"error": "duplicate_submit", "detail": "This draft was already submitted."}),
        409,
      )

    messages = _parse_messages(consult.get("messages_json"))
    app.logger.info(
      "TURN_BEGIN draft=%s turn=%s starting=%s focus=%s msg_chars=%s",
      str(draft_id).strip(),
      len(messages),
      starting,
      str(consult.get("active_focus") or "-"),
      len(message),
    )
    try:
      from client_intake_and_finmo import run_vitals as _run_vitals  # type: ignore
      _run_vitals.begin_turn(
        draft_id=str(draft_id).strip(),
        client_id=client_id,
        turn_index=len(messages),
        section=active_focus_current,
        starting=starting,
        message_chars=len(message),
      )
    except Exception:
      pass  # vitals capture is best-effort by contract; never blocks a turn

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
      # CW-013 PRODUCER-SIDE TRIPWIRE: the intake may not complete on a
      # draft the model-input contract would reject at submit. Stonewater
      # completed cleanly, submitted, and crashed on a G&A ratio in
      # percent-points - a full persona run burned discovering what this
      # check now catches turns earlier. Failure raises the same honest
      # hold as any judgment failure (never a verdict, never a silent
      # completion on an unbuildable draft).
      try:
        from client_intake_and_finmo.finmo_bridge import build_python_model_input_json  # type: ignore
        from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore
          SIDE_PRODUCER,
          validate_model_input_at_boundary,
        )

        _tw_ppe = _safe_float((financials_value or {}).get("initial_assets")) or 0.0
        _tw_mi = build_python_model_input_json(
          business_facts=dict(business_facts or {}),
          ops_json=ops_value or {},
          people_json=people_value or {},
          financials_json=financials_value or {},
          financials_year1_json=financials_year1_value or {},
          marketing_model_json=marketing_value or {},
          forecast_starting_ppe=_tw_ppe,
          maintenance_rate=0.05,
          controller_input_seed=[],
          forecast_quarters=[],
          business_name=str((business_facts or {}).get("business_name") or ""),
        )
        validate_model_input_at_boundary(_tw_mi, side=SIDE_PRODUCER)
      except Exception as _tw_exc:
        _tw_name = type(_tw_exc).__name__
        if "ContractViolation" in _tw_name:
          from client_intake_and_finmo.intake_coherence.section import (  # type: ignore
            CoherenceJudgmentUnavailable as _TwHold,
          )

          app.logger.error(
            "MODEL_INPUT_CONTRACT_FAILED_AT_COMPLETION draft=%s: %s",
            draft_id, str(_tw_exc)[:400],
          )
          raise _TwHold(
            "model_input_contract",
            f"completion-time model-input contract failure: {str(_tw_exc)[:300]}",
          )
        # Assembly preconditions (missing PPE etc.) are not contract
        # verdicts - log and let completion proceed as before.
        app.logger.warning(
          "completion-time model-input tripwire skipped draft=%s: %s: %s",
          draft_id, _tw_name, str(_tw_exc)[:200],
        )
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
        _ops_before = json.loads(json.dumps(ops_json)) if ops_json else {}
        ops_json = _apply_model_ops_patch(ops_json, turn.get("patch") if isinstance(turn, dict) else None)
        _ops_echo = _receipt_echo_line(_ops_before, ops_json, "ops")
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
        turn = {"assistant_message": _natural_continue(focus=str(focus or ""))}

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
        # An unexpected router action must never 500 the turn (the old
        # RuntimeError did). Re-ask the confirm naturally and keep the
        # capture window open.
        assistant_text = comp_router_msg or (
          f"{pending_competitive_advantage}\n\n{COMPETITIVE_ADVANTAGE_QUESTION}"
          if str(pending_competitive_advantage or "").strip()
          else COMPETITIVE_ADVANTAGE_QUESTION
        )
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
    # People rest-of-team payroll step: hand the router the same controller-style
    # frame the financials stages use, so a direct answer to the question becomes
    # an edit_patch instead of falling through to continue_chat (which would send
    # it to the people consultant and re-propose the review - a loop).
    rest_payroll_question_live = (
      str(focus).strip().lower() == "people"
      and _rest_of_team_payroll_pending(people_json, ops_json)
      and _REST_OF_TEAM_PAYROLL_MARKER in str(last_assistant or "")
    )
    if rest_payroll_question_live:
      shared_context_for_router = dict(shared_context_for_router or {})
      shared_context_for_router["people_controller"] = {
        "current_question": "rest_of_team_payroll",
        "patch_targets": ["people.rest_of_team_payroll_year1"],
      }

    # Coherence lever question live: give the router the round's options
    # (ids + exact numbers) so any natural phrasing of a choice becomes a
    # deterministic patch. Marker-gated on app-authored text only.
    from client_intake_and_finmo.intake_coherence import section as _coh_section
    coherence_round_live = (
      str(focus).strip().lower() == "financials"
      and _coh_section.walking_round_live(financials_json, last_assistant)
    )
    if coherence_round_live:
      _coh_frame = _coh_section.router_frame(financials_json)
      if _coh_frame:
        shared_context_for_router = dict(shared_context_for_router or {})
        shared_context_for_router["coherence_controller"] = _coh_frame
      else:
        coherence_round_live = False
    # Layer 1 (universal gate): an in-flight basis question travels with
    # ANY focus - the reply answers it wherever the conversation is, so
    # the router always sees the pending frame.
    _pending_any_focus = (financials_json or {}).get("_basis_clarify_pending")
    if isinstance(_pending_any_focus, dict) and _pending_any_focus:
      shared_context_for_router = dict(shared_context_for_router or {})
      shared_context_for_router["financials_controller"] = _build_financials_controller_context(
        None, financials_json=financials_json,
      )

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
      # While the rest-of-team payroll question is live, the client's answer often
      # reads like "that covers the whole team" - which this done-adding detector
      # would hijack into regenerating the people review before the router ever
      # sees the answer (an endless review<->question loop). The payroll answer
      # must reach the router; the review was already proposed anyway.
      and not rest_payroll_question_live
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

    # During a live coherence round, financials turns must reach the MAIN
    # router (the lever answers span sections); the direct financials
    # interview region below would swallow them.
    if str(focus).strip().lower() == "financials" and not coherence_round_live:
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

      # Incremental coherence heads-up: costs only accumulate, so a
      # mature-quarter EBITDA<0 on the partial stack is already stable
      # (no judgment can waive the sign invariant). Stamp it early for
      # the panel; the conversation itself opens at the firm-up point.
      try:
        from client_intake_and_finmo.intake_coherence import controller as _coh_ctl
        from client_intake_and_finmo.intake_coherence import section as _coh_sec
        _coh_state_early = _coh_sec.get_state(financials_json)
        if _coh_state_early.get("status") not in ("walking", "converged", "parked", "roadmap"):
          _early = _coh_ctl.evaluate_current(
            financials_json=financials_json,
            ops_json=ops_json,
            financials_year1_json=financials_year1_json,
            margin_band=None,
          )
          if _early is not None:
            _ebitda_neg = not (_early.get("checks") or {}).get("ebitda_positive", {}).get("passed", True)
            _coh_state_early["early_eval"] = {
              "stable_fail": bool(_ebitda_neg),
              "q11": _early.get("q11"),
            }
            financials_json = _coh_sec.put_state(financials_json, _coh_state_early)
      except Exception:
        pass

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
        _coh_turn, financials_json, _coh_suffix = _coherence_gate(
          ops_json=ops_json,
          people_json=people_json,
          market_json=market_json,
          marketing_model_json=_refresh_marketing_model(),
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          user_text=message,
        )
        if _coh_turn is not None:
          return _coherence_blocked_response(
            conn=conn,
            draft_id=draft_id,
            client_id=client_id,
            user_msg=user_msg,
            assistant_message=str(_coh_turn.get("assistant_message") or "").strip(),
            financials_json=financials_json,
            business_facts=business_facts,
          )
        if _coh_suffix:
          assistant_final = (assistant_final + _coh_suffix).strip()
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

    # Corrections to PROPOSER-GENERATED content (the competitive-advantage
    # hypothesis, milestone proposals) must be acknowledged in the moment -
    # the section consultant's follow-up never acks them, so suppressing the
    # router ack here made the app absorb the client's correction silently
    # and move on (CW-005/CW-007 deaf-to-client class).
    proposer_content_correction = False
    if competitive_intent_override:
      action = str(competitive_intent_override.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(competitive_intent_override.get("router_msg") or "").strip())
      patch = (
        competitive_intent_override.get("patch")
        if isinstance(competitive_intent_override.get("patch"), dict)
        else None
      )
      proposer_content_correction = action == "edit_patch"
    elif milestone_intent_override:
      action = str(milestone_intent_override.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(milestone_intent_override.get("router_msg") or "").strip())
      patch = (
        milestone_intent_override.get("patch")
        if isinstance(milestone_intent_override.get("patch"), dict)
        else None
      )
      proposer_content_correction = action == "edit_patch"
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
        # During the live ops interview, patches may only touch ops/business/
        # fulfillment fields (milestones only in the milestone-capture step) so a
        # normal answer cannot be hallucinated into an unrelated downstream field.
        ops_interview_filter={
          "enabled": str(focus).strip().lower() == "ops",
          "allow_milestones": bool(pending_ops_milestone),
        },
      )

      action = str(intent.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(intent.get("assistant_message") or "").strip())
      patch = intent.get("patch") if isinstance(intent.get("patch"), dict) else None

    # Anti-loop backstop for the rest-of-team payroll step: while the question is
    # live, a continue_chat/confirm_proceed fallthrough would run the people
    # consultant and re-propose the review (an endless review<->question cycle).
    # Re-ask crisply instead; the router's controller guidance resolves it on the
    # next answer.
    if (
      rest_payroll_question_live
      and action in ("continue_chat", "confirm_proceed")
      and not (isinstance(patch, dict) and any("rest_of_team_payroll_year1" in str(k) for k in patch.keys()))
    ):
      action = "confirm_clarify"
      router_msg = (
        f"Sorry - just to pin down {_REST_OF_TEAM_PAYROLL_MARKER}: about how much per year, "
        "roughly? And if it's only you and the people we've already covered, that's a "
        "perfectly good answer too."
      )
      patch = None

    # Same backstop for a live coherence round: a continue_chat fallthrough
    # would re-run the financials machinery and re-hit the gate cold. Re-ask
    # deterministically (marker included) so the controller frame survives.
    if (
      coherence_round_live
      and action == "continue_chat"
      and not (isinstance(patch, dict) and patch)
    ):
      _coh_reask = _coh_section.reask_message(financials_json)
      if _coh_reask:
        action = "confirm_clarify"
        router_msg = _coh_reask
        patch = None

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

    # Layer 1: resolve an in-flight basis question from ANY focus - the
    # resolution lands at source via the same applier the financials flow
    # uses, and the receipt-derived ack confirms only what was written.
    if (
      isinstance(_pending_any_focus, dict) and _pending_any_focus
      and isinstance(patch, dict)
    ):
      _res_any = patch.get("financials.basis_clarify_resolution") or patch.get("basis_clarify_resolution")
      if isinstance(_res_any, dict):
        _fin_res, _year1_res, _ack_res = _apply_basis_clarify_resolution(
          conn=conn,
          draft_id=str(draft_id).strip(),
          resolution={
            "basis": str(_res_any.get("basis") or "").strip().lower(),
            "amount": _safe_float(_res_any.get("amount")),
          },
          pending=_pending_any_focus,
          financials_json=dict(financials_json or {}),
          financials_year1_json=dict(financials_year1_json or {}),
          shared_context=dict(shared_context or {}),
          business_facts=business_facts,
        )
        financials_json, financials_year1_json = _fin_res, _year1_res
        _res_text = (_ack_res or "Got it.").strip()
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": _res_text}],
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          active_focus=focus,
          business_facts=business_facts,
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
            "assistant_message": _res_text,
          }
        )

    milestone_patch_from_user: Optional[List[Dict[str, Any]]] = None
    if action == "edit_patch" and isinstance(patch, dict):
      patch = _normalize_unscoped_patch(patch, focus=focus)
      # During a live coherence round the patch may legitimately span
      # sections (ops prices + the revenue anchor + cost fields); the
      # stage narrowing below would strip those, so it is bypassed.
      if str(focus or "").strip().lower() == "financials" and not coherence_round_live:
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

      # Coherence lever apply: option choices, custom prices (clamped to
      # the believable range, revenue anchor moved in the same write),
      # and the honest park. Remaining ordinary keys continue through
      # the generic scoped apply below.
      if coherence_round_live and isinstance(patch, dict):
        patch, ops_json, financials_json, _coh_notes = _coh_section.apply_router_patch(
          patch=patch,
          ops_json=ops_json,
          financials_json=financials_json,
        )
        shared_context["operating_model"] = ops_json
        shared_context["financials"] = financials_json
        if "parked" in _coh_notes:
          return _coherence_blocked_response(
            conn=conn,
            draft_id=draft_id,
            client_id=client_id,
            user_msg=user_msg,
            assistant_message=_coh_section.park_message(),
            financials_json=financials_json,
            business_facts=business_facts,
          )

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
      # Layer 2 (write-then-acknowledge): snapshot BEFORE the apply. The
      # acknowledgment for this turn is assembled from the diff of what
      # actually landed - never from the router's prose, which is a
      # sibling output of the same GPT call and can claim writes that
      # never happened (CW-008 false-confirmation class).
      _receipt_before = {
        "financials": json.loads(json.dumps(financials_json)) if financials_json else {},
        "ops": json.loads(json.dumps(ops_json)) if ops_json else {},
        "people": baseline_people_json,
        "market": json.loads(json.dumps(market_json)) if market_json else {},
      }
      # (c) A pending disclose-and-confirm routes STRUCTURALLY: an
      # affirmation (or a restated percent matching the proposal) lands
      # the proposed value before the patch applies, so the receipt
      # captures it as a real write. CW-012: "Yes - 75%" changed nothing
      # because only prose carried the question. One-shot: cleared
      # whatever the answer; a different figure routes normally.
      _lc_pending = (financials_json or {}).get("_lever_confirm_pending")
      if isinstance(_lc_pending, dict):
        financials_json = dict(financials_json or {})
        financials_json.pop("_lever_confirm_pending", None)
        try:
          _lc_msg = str(message or "").strip().lower()
          _lc_prop = _safe_float(_lc_pending.get("proposed"))
          _lc_affirm = bool(re.match(
            r"^\s*(yes|yep|yeah|right|correct|exactly|that'?s right|sounds right|looks right)\b",
            _lc_msg,
          ))
          _lc_restated = _lc_prop is not None and any(
            f > 0 and (abs(f / 100.0 - _lc_prop) <= 0.02 or abs(f - _lc_prop) <= 0.02)
            for f in _message_figures(_lc_msg)
          )
          if (_lc_affirm or _lc_restated) and _lc_prop is not None:
            _lc_lobs = (ops_json or {}).get("lob_models") or []
            _lc_prod = (_lc_lobs[int(_lc_pending["lob_index"])].get("products") or [])[
              int(_lc_pending["product_index"])
            ]
            _lc_prod[str(_lc_pending.get("field") or "utilization_rate")] = float(_lc_prop)
        except Exception:
          pass
      business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
        patch,
        business_facts=business_facts,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        fulfillment_json=fulfillment_json,
      )
      # CW-011 consequence contract: enforce BEFORE the receipt is built,
      # so the receipt and every ack downstream describe the kept truth -
      # an underivable second-lever move never survives long enough to
      # need disclosing as an accident.
      _driver_note = None
      try:
        ops_json, _driver_note = _reconcile_driver_correction(
          ops_before=_receipt_before["ops"],
          ops_after=ops_json,
          user_message=str(message or ""),
        )
        if isinstance(_driver_note, dict) and _driver_note.get("pending_frame"):
          financials_json = dict(financials_json or {})
          financials_json["_lever_confirm_pending"] = _driver_note["pending_frame"]
      except Exception:
        _driver_note = None
      # (b) current_revenue derivability guard (CW-012): an edit-turn
      # revenue write must be the CLIENT's number - the router asserted
      # "$996,000 you reported" for a total it computed itself (client
      # said $880,000). A revenue value matching no stated figure
      # reverts; the hold/propagate classifier owns revenue implied by
      # driver changes.
      try:
        _rev_before = _safe_float((_receipt_before.get("financials") or {}).get("current_revenue"))
        _rev_after = _safe_float((financials_json or {}).get("current_revenue"))
        if (
          _rev_before is not None and _rev_after is not None
          and abs(_rev_after - _rev_before) > max(1e-6, 0.001 * abs(_rev_before))
        ):
          _rev_figs = _message_figures(str(message or ""))
          _rev_ok = any(
            f > 0 and (
              abs(_rev_after - f) / f <= 0.02
              or abs(_rev_after - f * 1000.0) / (f * 1000.0) <= 0.02
            )
            for f in _rev_figs
          )
          if not _rev_ok:
            financials_json = dict(financials_json or {})
            financials_json["current_revenue"] = _rev_before
      except Exception:
        pass
      try:
        from client_intake_and_finmo.capture_receipt import numeric_receipt, receipt_summary  # type: ignore

        _edit_receipt = numeric_receipt(
          before=_receipt_before,
          after={
            "financials": financials_json or {},
            "ops": ops_json or {},
            "people": people_json or {},
            "market": market_json or {},
          },
          requested_fields=[
            str(k) for k, v in (patch or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
          ],
          clarify_pending=(financials_json or {}).get("_basis_clarify_pending"),
        )
        _edit_receipt_text = receipt_summary(_edit_receipt)
        # Layer 1 on the widest path: consult the universal gate for every
        # financials numeric this edit wrote, whatever the current focus.
        if not isinstance((financials_json or {}).get("_basis_clarify_pending"), dict):
          from client_intake_and_finmo.basis_gate import gate_numeric  # type: ignore

          _gate_det = {
            "revenue_driver": _detect_revenue_driver_basis_conflict,
            "stage_amount": _detect_stage_amount_basis_conflict,
            "percent_vs_dollar": _detect_percent_vs_dollar_conflict,
            "dollar_vs_percent": _detect_dollar_vs_percent_conflict,
          }
          _gate_ctx = {
            "financials_json": financials_json or {},
            "financials_year1_json": financials_year1_json or {},
          }
          for _wp, _old_v, _new_v in (_edit_receipt.get("written") or []):
            if not _wp.startswith("financials."):
              continue
            _leaf = _wp.split(".", 1)[1]
            _verd = gate_numeric(
              field=_wp, value=float(_new_v), stated_basis=None,
              user_message=str(message or ""), context=_gate_ctx, detectors=_gate_det,
            )
            if _verd.get("verdict") == "clarify" and _verd.get("pending"):
              financials_json = dict(financials_json or {})
              financials_json["_basis_clarify_pending"] = _verd["pending"]
              _edit_receipt["clarify"] = _verd["pending"]
              break
      except Exception:
        _edit_receipt = None
        _edit_receipt_text = ""
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

        # Established businesses must state the rest-of-team payroll (explicitly
        # excluding the owner and key people already counted) before People wraps.
        # Hold the section open and ask; the answer routes back through the router
        # as a people.rest_of_team_payroll_year1 patch and re-enters this path.
        if _rest_of_team_payroll_pending(people_json, ops_json):
          assistant_text = sanitize_fact_template(
            _build_rest_of_team_payroll_question("Got it - updated.")
          )
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
            active_focus=focus,
            business_facts=business_facts,
            people_json=people_json,
            financials_json=financials_json,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": focus,
              "awaiting_confirmation": True,
              "done": False,
              "action": "continue",
              "assistant_message": assistant_text,
            }
          )

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
        _ack_lead = "Got it - updated."
        _echo = _receipt_echo_line(baseline_people_json, people_json, "people")
        if _echo:
          _ack_lead = f"Got it - {_echo}."
        assistant_text = f"{_ack_lead}\n\nGreat, let's move on to Financials.\n\n{next_assistant}".strip()
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
        # Same rest-of-team gate as the edit path: an established business
        # answers the one payroll question before People hands off.
        if _rest_of_team_payroll_pending(people_json, ops_json):
          assistant_text = sanitize_fact_template(
            _build_rest_of_team_payroll_question("Got it.")
          )
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
            active_focus=focus,
            business_facts=business_facts,
            people_json=people_json,
            financials_json=financials_json,
          )
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id,
              "active_focus": focus,
              "awaiting_confirmation": True,
              "done": False,
              "action": "continue",
              "assistant_message": assistant_text,
            }
          )

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

        # AUTO-RE-CLOSE (CW-006 standstill): a post-completion correction used
        # to reopen the draft, acknowledge twice, and then WAIT - the draft sat
        # in_progress with Submit silently disabled until the client happened
        # to say something that drove another turn through completion. The app
        # must know when it is done, never depend on the client to break the
        # stall. Every section is still confirmed, the correction is already
        # applied - re-run the completion gate NOW, in this same turn: pass ->
        # re-closed with a specific naturalized acknowledgment and Submit live;
        # fail -> the walk engages honestly on the corrected numbers.
        if all((ops_confirmed, market_confirmed, people_confirmed, financials_confirmed)):
          # Layer 2: the re-close acknowledgment is receipt-first - it may
          # only claim what the write-set diff shows actually landed.
          # (f) CW-012: when the receipt is EMPTY but writes were
          # requested, router prose is the one voice that can still lie
          # ("I'll switch to 2.5" while nothing changed) - the say-do
          # note outranks it. Prose only speaks when nothing was asked.
          _requested_but_empty = bool(
            isinstance(_edit_receipt, dict)
            and not (_edit_receipt.get("written") or [])
            and (_edit_receipt.get("dropped") or [])
          )
          if _edit_receipt_text:
            ack_fallback = f"Updated: {_edit_receipt_text}."
          elif _requested_but_empty:
            # A dropped request whose STORED value already equals what
            # was asked is satisfied, not failed - a restatement acks as
            # agreement, never as "couldn't record".
            _unsat_leaves: List[str] = []
            _state_now = {"financials": financials_json or {}, "ops": ops_json or {}}
            for _fpath in (_edit_receipt.get("dropped") or []):
              _leafn = str(_fpath).rsplit(".", 1)[-1]
              _want = None
              for _pk, _pv in (patch or {}).items():
                if str(_pk).rsplit(".", 1)[-1] == _leafn and isinstance(_pv, (int, float)):
                  _want = float(_pv)
                  break
              _have = _find_numeric_leaf_value(_state_now, _leafn)
              if not (
                _want is not None and _have is not None
                and abs(_have - _want) <= max(1e-9, 0.005 * abs(_want))
              ):
                _unsat_leaves.append(_leafn.replace("_", " "))
            if _unsat_leaves:
              ack_fallback = (
                "I wasn't able to record "
                + " and ".join(_unsat_leaves[:3])
                + " just now - could you give me that once more?"
              )
            else:
              ack_fallback = "Got it - that matches what I already have on file."
          else:
            ack_fallback = str(router_msg or "").strip() or "Got it - updated."
          # CW-011 #2: a structural correction narrates DOLLARS the client
          # can verify (their stream), never internal lever values alone.
          if isinstance(_driver_note, dict):
            if _driver_note.get("confirm"):
              ack_fallback = (ack_fallback + str(_driver_note["confirm"])).strip()
            elif _driver_note.get("stream_note"):
              ack_fallback = (ack_fallback + str(_driver_note["stream_note"])).strip()
          try:
            from client_intake_and_finmo.recovery_phrasing import naturalize_recovery  # type: ignore

            ack_text = naturalize_recovery(
              closed_question=(
                "Acknowledge, in ONE warm specific sentence, exactly this change "
                f"the client just made (keep the numbers): {ack_fallback}"
              ),
              user_message=message,
              fallback=ack_fallback,
            )
          except Exception:
            ack_text = ack_fallback
          shared_live = dict(shared_context or {})
          shared_live["operating_model"] = ops_json
          shared_live["target_market"] = market_json
          shared_live["people_capability"] = people_json
          shared_live["financials"] = financials_json
          # RECONCILIATION SEMANTICS (CW-007): a POST-CONVERGENCE driver
          # correction is forward-looking information ("raising the price
          # next week"), not a restatement of the past - it must move the
          # revenue expectation, not be silently absorbed by a capacity
          # crush that pins the total to the old stated figure (which made
          # the readback repeat identical numbers after a price change).
          # Propagate the correction's implied-revenue delta into stated
          # revenue: factor = implied(new drivers) / implied(old drivers),
          # both computed from RAW assembles. Basis-FIX corrections (the
          # clarifier path) still reconcile drivers TO stated revenue -
          # there the stated number was right and the driver was misread.
          revenue_propagated = None
          revenue_reconciled = None
          try:
            pre_draft = get_draft(conn, draft_id=str(draft_id).strip())
            pre_ops = _parse_json_dict(pre_draft.get("operating_model_json"))
            pre_shared = dict(shared_live)
            pre_shared["operating_model"] = pre_ops
            pre_implied = _safe_float(
              (assemble_financials_year1(pre_shared, None) or {}).get("company_revenue_total_year1")
            )
            post_implied = _safe_float(
              (assemble_financials_year1(shared_live, None) or {}).get("company_revenue_total_year1")
            )
            stated = _safe_float(financials_json.get("current_revenue"))
            if pre_implied and post_implied and stated and pre_implied > 0:
              factor = post_implied / pre_implied
              # F1 (CW-009): classify the correction BEFORE propagating.
              # A STRUCTURE-FIX is the client repairing the model's misread
              # of a business that already exists; its fingerprint is that
              # the raw implied revenue moves INTO agreement with the
              # stated figure from the client's books (implied disagreed
              # before, agrees better after). Stated revenue is reality
              # there - multiplying it by the ratio re-applies the model's
              # old error on top of the client's truth (Ironclad: periods
              # 12->38 inflated $1,050,000 to $1,220,184). A VALUE change
              # (a price rise) starts from a model already in agreement
              # and moves it AWAY - only then does stated revenue follow
              # the drivers.
              pre_gap = abs(pre_implied - stated) / stated
              post_gap = abs(post_implied - stated) / stated
              structure_fix = pre_gap > 0.08 and post_gap < pre_gap
              if abs(factor - 1.0) > 0.005 and not structure_fix:
                financials_json = dict(financials_json)
                financials_json["current_revenue"] = float(stated * factor)
                revenue_propagated = financials_json["current_revenue"]
              elif structure_fix and post_gap < 0.05:
                revenue_reconciled = float(stated)
          except Exception:
            pass
          try:
            financials_year1_json = assemble_financials_year1(shared_live, financials_year1_json)
          except Exception:
            pass
          _coh_turn, financials_json, _coh_suffix = _coherence_gate(
            ops_json=ops_json,
            people_json=people_json,
            market_json=market_json,
            marketing_model_json=_refresh_marketing_model(),
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            user_text=message,
          )
          if _coh_turn is not None:
            blocked_message = (
              f"{ack_text}\n\n{str(_coh_turn.get('assistant_message') or '').strip()}"
            ).strip()
            return _coherence_blocked_response(
              conn=conn,
              draft_id=draft_id,
              client_id=client_id,
              user_msg=user_msg,
              assistant_message=blocked_message,
              financials_json=financials_json,
              business_facts=business_facts,
            )
          carried_note = ""
          if revenue_propagated:
            carried_note = (
              f" I've carried that through your numbers - annual revenue now sits at "
              f"about {_format_currency(revenue_propagated)}."
            )
          elif revenue_reconciled:
            carried_note = (
              f" Your unit model now lines up with the "
              f"{_format_currency(revenue_reconciled)} you reported - annual revenue "
              f"stays as you stated it."
            )
          assistant_final = (
            f"{ack_text}\n\nYou're all set - the intake is complete again and you "
            f"can submit whenever you're ready.{carried_note}"
          )
          if _coh_suffix:
            assistant_final = (assistant_final + _coh_suffix).strip()
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

      # For edit patches, the intent router is used only to interpret intent and
      # produce the deterministic patch. The domain consultant generates the next
      # conversational turn. Showing both messages causes duplicated acknowledgements
      # and repeated questions.
      #
      # Exception: if the edit re-opens a completed intake into final review, keep the
      # router acknowledgement so the user clearly sees the update before the audit.
      # Second exception: corrections to proposer-generated content ALWAYS lead
      # with the acknowledgment, naturalized and specific - the consultant
      # follow-up never acks these, and silence here is the deaf-to-client bug.
      assistant_text = (
        router_msg
        if (confirm_question_live or active_focus_out != focus or proposer_content_correction)
        else ""
      )
      # Layer 2: numeric acknowledgments come FROM THE RECEIPT - what the
      # diff of persisted state says actually changed. The router's prose
      # is used only for non-numeric content (e.g. the advantage text).
      # Nothing written but numerics requested -> the say-do note, never a
      # confident ack. A pending clarifier owns its own turn upstream.
      if _edit_receipt is not None and _edit_receipt.get("clarify"):
        # Layer 1 ask-turn on this path: the gate flagged a written value
        # as ambiguous - the turn becomes the propose-confirm question
        # (with the receipt of what DID store leading, so nothing said
        # outruns the writes).
        _clar_q = _build_basis_clarify_message(
          _edit_receipt["clarify"], user_message=str(message or "")
        )
        assistant_text = (
          f"Updated: {_edit_receipt_text}.\n\n{_clar_q}" if _edit_receipt_text else _clar_q
        ).strip()
      elif _edit_receipt is not None and (_edit_receipt.get("written") or _edit_receipt.get("dropped")):
        if _edit_receipt_text:
          _ack_base = f"Updated: {_edit_receipt_text}."
          try:
            from client_intake_and_finmo.recovery_phrasing import naturalize_recovery  # type: ignore

            assistant_text = naturalize_recovery(
              closed_question=(
                "Acknowledge, in ONE warm sentence, exactly these recorded "
                f"updates (keep every figure): {_ack_base}"
              ),
              user_message=message,
              fallback=_ack_base,
            )
          except Exception:
            assistant_text = _ack_base
        elif _edit_receipt.get("dropped"):
          _drop_note = _unapplied_fields_note(
            [str(f).split(".", 1)[-1] for f in _edit_receipt["dropped"]]
          )
          assistant_text = (_drop_note or "I wasn't able to apply that change yet.").strip()
      elif proposer_content_correction and assistant_text:
        try:
          from client_intake_and_finmo.recovery_phrasing import naturalize_recovery  # type: ignore

          assistant_text = naturalize_recovery(
            closed_question=(
              "Acknowledge, in ONE warm specific sentence, exactly this correction "
              f"the client just made to your proposal: {assistant_text}"
            ),
            user_message=message,
            fallback=assistant_text,
          )
        except Exception:
          pass
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
            _coh_turn, financials_json, _coh_suffix = _coherence_gate(
              ops_json=ops_json,
              people_json=people_json,
              market_json=market_json,
              marketing_model_json=_refresh_marketing_model(),
              financials_json=financials_json,
              financials_year1_json=financials_year1_json,
              user_text=message,
            )
            if _coh_turn is not None:
              return _coherence_blocked_response(
                conn=conn,
                draft_id=draft_id,
                client_id=client_id,
                user_msg=user_msg,
                assistant_message=str(_coh_turn.get("assistant_message") or "").strip(),
                financials_json=financials_json,
                business_facts=business_facts,
              )
            if _coh_suffix:
              assistant_final = (assistant_final + _coh_suffix).strip()
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
                conversation_messages=messages,
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

            _fin_before = json.loads(json.dumps(ops_json)) if ops_json else {}
            ops_json = final_obj
            _finalize_echo = _receipt_echo_line(_fin_before, final_obj, "ops")
            if _finalize_echo:
              _pending_finalize_note = f"While finalizing I tidied the numbers: {_finalize_echo}."
            else:
              _pending_finalize_note = ""
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
            _fin_note = (_pending_finalize_note + "\n\n") if _pending_finalize_note else ""
            assistant_text = f"{_fin_note}Great, let's move on to Target Market.\n\n{next_assistant}".strip()
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
      # Third people->financials advance path (pure approval, no edits): the same
      # rest-of-team payroll gate as the edit and counter paths. An established
      # business answers the one payroll question before People hands off.
      if (
        str(focus).strip().lower() == "people"
        and _rest_of_team_payroll_pending(people_json, ops_json)
      ):
        assistant_text = sanitize_fact_template(
          _build_rest_of_team_payroll_question("Great.")
        )
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          active_focus=focus,
          business_facts=business_facts,
          people_json=people_json,
          financials_json=financials_json,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": focus,
            "awaiting_confirmation": True,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

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
        next_assistant = _natural_continue(focus=str(next_focus or ""))

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
        _coh_turn, financials_json, _coh_suffix = _coherence_gate(
          ops_json=ops_json,
          people_json=people_json,
          market_json=market_json,
          marketing_model_json=_refresh_marketing_model(),
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          user_text=message,
        )
        if _coh_turn is not None:
          return _coherence_blocked_response(
            conn=conn,
            draft_id=draft_id,
            client_id=client_id,
            user_msg=user_msg,
            assistant_message=str(_coh_turn.get("assistant_message") or "").strip(),
            financials_json=financials_json,
            business_facts=business_facts,
          )
        if _coh_suffix:
          next_assistant = (next_assistant + _coh_suffix).strip()
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
      turn = {"assistant_message": _natural_continue(focus=str(focus or "")), "finalize_ready": False}

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
      _ops_before = json.loads(json.dumps(ops_json)) if ops_json else {}
      ops_json = _apply_model_ops_patch(ops_json, turn.get("patch"))
      _ops_echo = _receipt_echo_line(_ops_before, ops_json, "ops")
      if _ops_echo:
        # Layer 2: every numeric write is SAID, from the write-set - the
        # consultant's prose never confirms numbers (prompt contract), the
        # app does, downstream of the write.
        assistant_text = (assistant_text + "\n\n(Noted: " + _ops_echo + ".)").strip()
      # CW-011 #3 (B hardening) - the PROSE receipt: when a proposal field
      # changes from a prior non-empty value on a client turn, the
      # reflection is built from the STORED value and prepended
      # structurally. The prompt rule stays (it reads better when the GPT
      # complies), but the reflection no longer depends on it: CW-010
      # passed and CW-011 failed on identical code - compliance is
      # probabilistic, receipts are not.
      try:
        _adv_old = str((_ops_before or {}).get("competitive_advantage") or "").strip()
        _adv_new = str((ops_json or {}).get("competitive_advantage") or "").strip()
        if _prose_reflection_needed(
          old_value=_adv_old, new_value=_adv_new,
          assistant_text=assistant_text, user_message=str(message or ""),
        ):
          _reflection = f"Noted - your edge, in your words: {_adv_new}"
          try:
            from client_intake_and_finmo.recovery_phrasing import naturalize_recovery  # type: ignore

            _reflection = naturalize_recovery(
              closed_question=(
                "In ONE warm sentence, reflect back the competitive edge the "
                f"client just corrected, keeping its substance: {_adv_new}"
              ),
              user_message=str(message or ""),
              fallback=_reflection,
            )
          except Exception:
            pass
          assistant_text = (str(_reflection).strip() + "\n\n" + assistant_text).strip()
      except Exception:
        pass
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
          for _pp in (extracted_people_list or []):
            if isinstance(_pp, dict) and _pp.get("annual_wage") is not None and not _pp.get("wage_source"):
              # Client-stated wages (the extractor keeps null unless stated)
              # get capture provenance so OEWS enrichment may never
              # silently replace them (CW-005 #14 family).
              _pp["wage_source"] = "client_override"
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
            f"For planning purposes, what average utilization do you want to assume for {util_label} "
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
        conversation_messages=messages,
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
      _coh_turn, financials_json, _coh_suffix = _coherence_gate(
        ops_json=ops_json,
        people_json=people_json,
        market_json=market_json,
        marketing_model_json=_refresh_marketing_model(),
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        user_text=message,
      )
      if _coh_turn is not None:
        return _coherence_blocked_response(
          conn=conn,
          draft_id=draft_id,
          client_id=client_id,
          user_msg=user_msg,
          assistant_message=str(_coh_turn.get("assistant_message") or "").strip(),
          financials_json=financials_json,
          business_facts=business_facts,
        )
      if _coh_suffix:
        assistant_final = (assistant_final + _coh_suffix).strip()
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
          conversation_messages=messages,
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
      _fin_before = json.loads(json.dumps(market_json)) if market_json else {}
      market_json = final_obj
      _finalize_echo = _receipt_echo_line(_fin_before, final_obj, "market")

      # Show the finalized marketing_plan_summary to the client for confirmation/counter
      # before advancing. This replaces the older in-chat "promotion model" proposal.
      assistant_final = sanitize_fact_template(
        str((market_json or {}).get("marketing_plan_summary") or "").strip()
      )
      if _finalize_echo:
        assistant_final = (
          assistant_final + "\n\n(Adjusted while finalizing: " + _finalize_echo + ".)"
        ).strip()
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
      _fin_before = json.loads(json.dumps(people_json)) if people_json else {}
      people_json = final_obj
      _finalize_echo = _receipt_echo_line(_fin_before, final_obj, "people")

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
          "Review this draft (key people narrative + suggested roles with wages and timing) and tell me any changes."
        )
      elif has_people:
        parts.append("Review this draft (key people narrative) and tell me any changes.")
      elif has_roles:
        parts.append("Review these suggested roles (with wages and timing) and tell me any changes.")

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
    user_turn_to_persist = (
      [] if starting else [{"role": "user", "content": message}]
    )
    hold_message = _transient_judgment_hold_message(exc)
    if hold_message is not None:
      # Transient judgment failure: honest hold, never a verdict. The
      # turn (client message + hold) is committed so nothing is lost
      # and the next send re-enters exactly where this one stopped.
      app.logger.warning(
        "TURN_HOLD draft=%s transient judgment failure: %s", draft_id, exc
      )
      try:
        from client_intake_and_finmo import run_vitals as _run_vitals  # type: ignore
        _run_vitals.mark_turn_hold(str(exc))
      except Exception:
        pass
      try:
        # CW-010: stamp the consecutive-hold count so a HELD turn's
        # arbitration re-author can carry a fresh-roll nonce (the GPT
        # lock otherwise replays the same contradictory judgment forever
        # - fail-loud became fail-forever). Underscore key: internal,
        # never in receipts; cleared on judgment success.
        _hold_fin = None
        if "coherence_judgment_unavailable" in str(exc):
          try:
            _hold_row = get_draft_runtime_row(conn, draft_id=str(draft_id).strip())
            _hold_fin = _parse_json_dict(_hold_row.get("financials_json"))
            _hold_fin["_judgment_hold_retries"] = (
              int(_hold_fin.get("_judgment_hold_retries") or 0) + 1
            )
          except Exception:
            _hold_fin = None
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[
            *user_turn_to_persist,
            {"role": "assistant", "content": hold_message},
          ],
          financials_json=_hold_fin,
        )
      except Exception:
        app.logger.exception("TURN_HOLD persist failed draft=%s", draft_id)
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": active_focus_current,
          "awaiting_confirmation": True,
          "done": False,
          "action": "hold",
          "assistant_message": hold_message,
        }
      )
    app.logger.exception("Failed intake consult: %s", exc)
    # Fail loud, but never lose the client's words: persist the user
    # turn before surfacing the error.
    try:
      if user_turn_to_persist:
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=user_turn_to_persist,
        )
    except Exception:
      app.logger.exception("post-error user-turn persist failed draft=%s", draft_id)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
  finally:
    try:
      conn.close()
    except Exception:
      pass
