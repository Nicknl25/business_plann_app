"""Iter 19 Stage 5 — Stage ramp handler orchestrator.

Public entry points:

  - :func:`run_stage_ramp_handler` — given a Python-built contract +
    its validator failure, runs the GPT tool-calling session to
    refine the contract. Returns the refined contract (RESOLVED) or
    hard-fails with the residual diagnostic (EXHAUSTED).
  - :func:`engage_stage_ramp_handler_on_validator_failure` —
    production wiring entry point. Tries Python first; only invokes
    the handler when the validator rejects the Python output.

Doctrine §5 invariants:

1. Module location: this package.
2. Defined authority: ``stage_ramp_contract`` grid fields per
   :data:`STAGE_RAMP_FIELD_AUTHORITY`.
3. ``HARD_CAP_TOOL_CALLS = 10`` (in :mod:`tool_calling_session`).
4. ``counts_against_run_budget=False`` on every API call.
5. Specific validator trigger: ``_validate_stage_ramp_contract_payload``
   raising ``RuntimeError``.
6. Specific hard-fail diagnostic: :class:`StageRampHandlerStatus`
   ``EXHAUSTED`` with the residual validator error text.
"""

from __future__ import annotations

import contextvars
import copy
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 9 P3.12 — machinery fail-fast helpers for the stage ramp handler.
#
# Mirror of the funding handler's machinery helpers
# (post_intake_funding_handler/handler.py). Per doctrine §5b machinery
# fail-fasts protect the iteration/handler infrastructure itself from
# silent degradation, distinct from validators.
# ---------------------------------------------------------------------------


_STAGE_RAMP_HANDLER_GPT_CALL_COUNT: "contextvars.ContextVar[Optional[int]]" = (
  contextvars.ContextVar(
    "stage_ramp_handler_gpt_call_count",
    default=None,
  )
)


def _stage_ramp_handler_machinery_fail_fast(
  operation: str,
  message: str,
  details: Optional[Dict[str, Any]] = None,
) -> None:
  """Hard-stop on a stage-ramp-handler machinery malfunction."""
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
  )
  raise PostIntakePreconditionFailed(
    operation=str(operation or "").strip() or "stage_ramp_handler_machinery_violation",
    pipeline_stage="stage_ramp_handler",
    expected="stage ramp handler iteration/handler machinery intact",
    actual=str(message or "").strip()[:600],
    details=details or {},
  )


def _assert_stage_ramp_handler_state_intact(
  *,
  round_n: int,
  input_items: Any,
  history: Any,
  verified_commit_candidate: Any,
) -> None:
  """Machinery invariant #3 — state corruption between rounds."""
  if not isinstance(input_items, list) or not input_items:
    _stage_ramp_handler_machinery_fail_fast(
      "stage_ramp_handler_state_corruption_between_rounds",
      f"round {round_n} entered with malformed input_items",
      details={"round_n": int(round_n), "input_items_type": type(input_items).__name__},
    )
  for idx, item in enumerate(input_items):
    if not isinstance(item, dict):
      _stage_ramp_handler_machinery_fail_fast(
        "stage_ramp_handler_state_corruption_between_rounds",
        f"round {round_n} input_items[{idx}] is not a dict (got {type(item).__name__})",
        details={"round_n": int(round_n), "bad_index": idx},
      )
  if not isinstance(history, list):
    _stage_ramp_handler_machinery_fail_fast(
      "stage_ramp_handler_state_corruption_between_rounds",
      f"round {round_n} history is not a list",
      details={"round_n": int(round_n), "history_type": type(history).__name__},
    )
  if verified_commit_candidate is not None and not hasattr(verified_commit_candidate, "arguments"):
    _stage_ramp_handler_machinery_fail_fast(
      "stage_ramp_handler_state_corruption_between_rounds",
      f"round {round_n} verified_commit_candidate set but lacks 'arguments' attr",
      details={"round_n": int(round_n)},
    )


def _assert_stage_ramp_handler_budget_decoupled(
  *,
  round_n: int,
  counts_against_run_budget_arg: bool,
) -> None:
  """Machinery invariant #2 — budget decoupling violation."""
  if counts_against_run_budget_arg is not False:
    _stage_ramp_handler_machinery_fail_fast(
      "stage_ramp_handler_budget_decoupling_violation",
      (
        f"round {round_n} GPT call site passed counts_against_run_budget="
        f"{counts_against_run_budget_arg!r}; the stage ramp handler's "
        "session must always pass False to bound calls by the handler's "
        "HARD_CAP_TOOL_CALLS=10 rather than the run-wide budget."
      ),
      details={"round_n": int(round_n), "passed_value": counts_against_run_budget_arg},
    )


def _assert_stage_ramp_handler_round_count_consistent(
  *,
  loop_round_index: int,
  gpt_calls_made: int,
) -> None:
  """Machinery invariant #1 — round count drift (post-call)."""
  expected = _STAGE_RAMP_HANDLER_GPT_CALL_COUNT.get()
  if expected is None:
    _stage_ramp_handler_machinery_fail_fast(
      "stage_ramp_handler_round_count_drift",
      f"contextvar not initialized at loop round {loop_round_index}",
      details={"loop_round_index": int(loop_round_index)},
    )
  if int(expected) != int(gpt_calls_made):
    _stage_ramp_handler_machinery_fail_fast(
      "stage_ramp_handler_round_count_drift",
      (
        f"loop round {loop_round_index}: contextvar gpt_call_count="
        f"{expected} but gpt_calls_made={gpt_calls_made}; counter divergence"
      ),
      details={
        "loop_round_index": int(loop_round_index),
        "contextvar_count": int(expected),
        "gpt_calls_made": int(gpt_calls_made),
      },
    )


def _assert_stage_ramp_handler_authority_respected(
  *,
  refined_contract: Any,
) -> None:
  """Machinery invariant #4 — authority violation. The refined
  contract must only contain fields declared in
  STAGE_RAMP_FIELD_AUTHORITY. The strict-mode JSON schema already
  enforces this at parse time; this guard catches any post-parse
  mutation (e.g., handler-side post-processing that adds fields).
  """
  if not isinstance(refined_contract, dict):
    return
  declared_root_fields = {
    "stage_family",
    "utilization_high_watermark",
    "quarter_ramp_grid",
    "rationale",
  }
  # Also allow provenance fields the engage helper adds.
  declared_root_fields |= {
    "business_stage",
    "business_stage_source",
    "planning_mode",
    "planning_mode_reason",
    "decision_source",
    "contract_version",
    "r_and_d_applicability",
    "python_proposal_diagnostic",
  }
  out_of_authority = [
    str(key) for key in refined_contract.keys()
    if str(key) not in declared_root_fields
  ]
  if out_of_authority:
    _stage_ramp_handler_machinery_fail_fast(
      "stage_ramp_handler_authority_violation",
      (
        f"refined_contract includes {len(out_of_authority)} root field(s) "
        "outside the stage ramp handler's declared authority"
      ),
      details={
        "out_of_authority_fields": out_of_authority[:10],
        "declared_root_fields": sorted(declared_root_fields),
      },
    )


STAGE_RAMP_FIELD_AUTHORITY: List[str] = [
  "stage_ramp_contract.stage_family",
  "stage_ramp_contract.utilization_high_watermark",
  "stage_ramp_contract.quarter_ramp_grid[].rev_target",
  "stage_ramp_contract.quarter_ramp_grid[].rev_max",
  "stage_ramp_contract.quarter_ramp_grid[].rev_spike",
  "stage_ramp_contract.quarter_ramp_grid[].rev_spike_max",
  "stage_ramp_contract.quarter_ramp_grid[].max_util",
  "stage_ramp_contract.quarter_ramp_grid[].cogs_target",
  "stage_ramp_contract.quarter_ramp_grid[].cogs_max",
  "stage_ramp_contract.quarter_ramp_grid[].marketing_max",
  "stage_ramp_contract.quarter_ramp_grid[].rd_max",
  "stage_ramp_contract.quarter_ramp_grid[].ga_max",
  "stage_ramp_contract.quarter_ramp_grid[].lease_max",
  "stage_ramp_contract.quarter_ramp_grid[].ni_floor",
  "stage_ramp_contract.quarter_ramp_grid[].posture",
  "stage_ramp_contract.rationale",
]


class StageRampHandlerStatus(Enum):
  RESOLVED = "resolved"
  EXHAUSTED = "exhausted"
  NO_VIOLATIONS = "no_violations"


@dataclass
class StageRampHandlerResult:
  status: StageRampHandlerStatus
  refined_contract: Optional[Dict[str, Any]] = None
  tool_calls_used: int = 0
  diagnostic: str = ""
  validator_error_text: str = ""
  session_status: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status.value,
      "refined_contract_keys": (
        sorted(self.refined_contract.keys()) if isinstance(self.refined_contract, dict) else []
      ),
      "tool_calls_used": int(self.tool_calls_used),
      "diagnostic": self.diagnostic,
      "validator_error_text": self.validator_error_text,
      "session_status": self.session_status,
    }


def run_stage_ramp_handler(
  *,
  python_contract: Dict[str, Any],
  validator_error_text: str,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  stage_policy: Optional[Dict[str, Any]] = None,
  r_and_d_enabled: bool = True,
  _run_gpt_session: Optional[Callable[..., Any]] = None,
  _validator: Optional[Callable[..., Dict[str, Any]]] = None,
) -> StageRampHandlerResult:
  """Run the GPT tool-calling session to refine the Python-built
  stage ramp contract until the validator accepts it.

  ``_run_gpt_session`` and ``_validator`` are test seams — production
  callers pass None to use the real implementations.
  """
  session_runner = _run_gpt_session
  if session_runner is None:
    from client_intake_and_finmo.post_intake_stage_ramp_handler.tool_calling_session import (  # type: ignore
      run_stage_ramp_tool_calling_session,
    )
    session_runner = run_stage_ramp_tool_calling_session

  validator = _validator
  if validator is None:
    from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
      _validate_stage_ramp_contract_payload,
    )
    validator = _validate_stage_ramp_contract_payload

  expected_family = str((stage_policy or {}).get("stage_family") or python_contract.get("stage_family") or "operational")
  business_stage = str(python_contract.get("business_stage") or "")
  planning_mode = str(python_contract.get("planning_mode") or "")
  planning_mode_reason = str(python_contract.get("planning_mode_reason") or "")

  session_result = session_runner(
    python_contract=copy.deepcopy(python_contract),
    validator_error_text=validator_error_text,
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    stage_policy=stage_policy or {},
    r_and_d_enabled=r_and_d_enabled,
  )

  refined = getattr(session_result, "refined_contract", None)
  status_str = str(getattr(session_result, "status", "") or "")
  tool_calls_used = int(getattr(session_result, "tool_calls_used", 0) or 0)
  detail = str(getattr(session_result, "detail", "") or "")

  if status_str != "verified" or not isinstance(refined, dict):
    return StageRampHandlerResult(
      status=StageRampHandlerStatus.EXHAUSTED,
      refined_contract=None,
      tool_calls_used=tool_calls_used,
      diagnostic=(
        f"stage_ramp_handler_{status_str or 'unknown'}: GPT session "
        f"did not produce a validator-accepted contract. "
        f"validator_error={validator_error_text[:300]} session_detail={detail[:200]}"
      ),
      validator_error_text=validator_error_text,
      session_status=status_str,
    )

  # Verify the refined contract one more time against the production
  # validator — the session's per-turn validator probe is a mirror;
  # this is the canonical check.
  try:
    validator(
      payload=refined,
      expected_stage_family=expected_family,
      business_stage=business_stage,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      r_and_d_enabled=r_and_d_enabled,
    )
  except RuntimeError as exc:
    return StageRampHandlerResult(
      status=StageRampHandlerStatus.EXHAUSTED,
      refined_contract=None,
      tool_calls_used=tool_calls_used,
      diagnostic=(
        "stage_ramp_handler_post_session_validator_failed: refined "
        f"contract failed canonical validator after session reported "
        f"verified status. error={str(exc)[:300]}"
      ),
      validator_error_text=str(exc),
      session_status=status_str,
    )

  return StageRampHandlerResult(
    status=StageRampHandlerStatus.RESOLVED,
    refined_contract=refined,
    tool_calls_used=tool_calls_used,
    diagnostic="stage_ramp_handler_refined_contract_validator_accepted",
    validator_error_text=validator_error_text,
    session_status=status_str,
  )


def engage_stage_ramp_handler_on_validator_failure(
  *,
  build_python_contract: Callable[..., Dict[str, Any]],
  validator: Callable[..., Dict[str, Any]],
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  r_and_d_applicability: Optional[Dict[str, Any]] = None,
  stage_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Production wiring entry point. Replaces the legacy GPT-only
  ``_estimate_stage_ramp_contract_with_gpt`` invocation.

  Pipeline:
    1. ``build_python_contract`` (Python deterministic builder).
    2. ``validator`` on Python output.
    3. If validator passes: return Python contract.
    4. If validator fails: invoke :func:`run_stage_ramp_handler`.
    5. If handler RESOLVED: return refined contract.
    6. If handler EXHAUSTED: raise RuntimeError with the specific
       residual diagnostic (doctrine §1).

  Returns the accepted contract dict. Raises RuntimeError on
  handler exhaustion.
  """
  python_contract = build_python_contract(
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    people_json=people_json or {},
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    model_input_json=model_input_json or {},
    finmo_json=finmo_json or {},
    r_and_d_applicability=r_and_d_applicability or {},
  )
  expected_family = str(python_contract.get("stage_family") or "operational")
  # Derive business_stage from ops/facts since the validator-clean
  # builder output does not carry it.
  business_stage = (
    str((ops_json or {}).get("business_stage") or "").strip().lower()
    or str((business_facts or {}).get("business_stage") or "").strip().lower()
    or expected_family
  )
  r_and_d_enabled = (
    bool(r_and_d_applicability.get("r_and_d_enabled"))
    if isinstance(r_and_d_applicability, dict)
    and isinstance(r_and_d_applicability.get("r_and_d_enabled"), bool)
    else True
  )

  def _annotate_provenance(contract: Dict[str, Any], *, decision_source: str) -> Dict[str, Any]:
    """Add the orchestrator-expected provenance fields after the
    validator accepts. Builder + handler outputs are validator-clean;
    provenance is layered on at the engagement boundary."""
    annotated = copy.deepcopy(contract)
    annotated["decision_source"] = decision_source
    annotated["business_stage"] = business_stage
    annotated["business_stage_source"] = (
      "ops.business_stage"
      if (ops_json or {}).get("business_stage")
      else "business_start_date_inferred"
    )
    annotated["planning_mode"] = str(planning_mode or "").strip().lower()
    annotated["planning_mode_reason"] = str(planning_mode_reason or "").strip()
    annotated["r_and_d_applicability"] = copy.deepcopy(r_and_d_applicability or {})
    annotated["contract_version"] = "stage_ramp_contract_v2"
    return annotated

  try:
    validator(
      payload=python_contract,
      expected_stage_family=expected_family,
      business_stage=business_stage,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      r_and_d_enabled=r_and_d_enabled,
    )
  except RuntimeError as exc:
    # Python output rejected — escalate to handler.
    handler_result = run_stage_ramp_handler(
      python_contract=python_contract,
      validator_error_text=str(exc),
      business_facts=business_facts or {},
      ops_json=ops_json or {},
      stage_policy=stage_policy or {},
      r_and_d_enabled=r_and_d_enabled,
      _validator=validator,  # Thread the same validator down so the
                              # handler's post-session canonical check
                              # uses the caller's validator.
    )
    if handler_result.status != StageRampHandlerStatus.RESOLVED:
      raise RuntimeError(handler_result.diagnostic) from exc
    refined = handler_result.refined_contract or {}
    # Phase 9 P3.12 — machinery invariant #4: authority violation.
    _assert_stage_ramp_handler_authority_respected(refined_contract=refined)
    annotated = _annotate_provenance(refined, decision_source="stage_ramp_handler_refined")
    annotated["python_proposal_diagnostic"] = {
      "validator_error_text": handler_result.validator_error_text,
      "tool_calls_used": handler_result.tool_calls_used,
      "diagnostic": handler_result.diagnostic,
    }
    return annotated
  # Python contract passed the validator directly.
  return _annotate_provenance(python_contract, decision_source="python_deterministic_builder")
