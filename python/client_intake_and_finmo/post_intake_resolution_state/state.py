"""Phase 8 — resolution-state replacement (formerly post_intake_issues).

Each function in this file replaces a bound helper that the legacy
post_intake_issues/runner.py used to inject into other modules' globals.
The replacements are intentionally small and shape-stable: they build
the same dict shapes downstream readers expect, populated from the new
architecture (realism gate per-metric output + cascade diagnostics)
when those are available, or honest empty defaults when they aren't.

Design:
  - Honest empty defaults (`all_cleared=True, remaining_issues=[]`) are
    fine because the new authority on "is this run resolved?" is the
    acceptance gate, which queries the realism gate and
    solver_target_assertion directly. The controller_resolution_state
    becomes a thin compatibility shim — its `all_cleared` no longer
    drives any abort or completion decision.
  - Where the legacy issue-code vocabulary leaked into downstream
    schemas (e.g. realism_memo_json), we keep the keys but treat the
    realism gate's hard_fail metric_keys as the closest analog.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence


def empty_controller_resolution_state() -> Dict[str, Any]:
  """Phase 8 — the dict shape callers used to read from. The legacy
  fields are kept (with cleared defaults) so downstream readers don't
  KeyError on legacy field names."""
  return {
    "all_cleared": True,
    "remaining_issues": [],
    "remaining_issue_count": 0,
    "resolved_issues": [],
    "resolved_issue_count": 0,
    "tolerated_issues": [],
    "tolerated_issue_count": 0,
    "iteration_pending_issues": [],
    "iteration_pending_issue_count": 0,
    "issue_status_records": [],
    "controller_resolution_state_version": "phase_8_no_issue_machinery",
  }


def empty_realism_memo() -> Dict[str, Any]:
  return {
    "realism_gate": {"line_level": {"results": [], "warnings": []}},
    "results": [],
    "warnings": [],
    "memo_version": "phase_8_no_issue_machinery",
  }


def empty_resolution_summary() -> Dict[str, Any]:
  return {
    "all_cleared": True,
    "issue_summaries": [],
    "phase_issue_counts": {},
    "summary_version": "phase_8_no_issue_machinery",
  }


def _safe_int(value: Any) -> Optional[int]:
  try:
    return int(round(float(value)))
  except Exception:
    return None


def _realism_results_from(realism_gate_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  if not isinstance(realism_gate_payload, dict):
    return []
  results = realism_gate_payload.get("results")
  if isinstance(results, list):
    return [r for r in results if isinstance(r, dict)]
  line_level = realism_gate_payload.get("line_level")
  if isinstance(line_level, dict):
    nested = line_level.get("results")
    if isinstance(nested, list):
      return [r for r in nested if isinstance(r, dict)]
  return []


def realism_gate_hard_fail_metric_keys(
  realism_gate_payload: Optional[Dict[str, Any]],
) -> List[str]:
  out: List[str] = []
  for r in _realism_results_from(realism_gate_payload):
    status = str(r.get("status") or "").strip().lower()
    gate_kind = str(r.get("gate_kind") or "").strip().lower()
    # Phase 9 audit fix #1 — match the validator's actual status value
    # ("out_of_band_hard_fail") in addition to the legacy aliases.
    if status in ("hard_fail", "violation_hard_fail", "out_of_band_hard_fail") or (
      status == "fail" and gate_kind == "hard_fail"
    ):
      key = str(r.get("metric_key") or "").strip()
      if key and key not in out:
        out.append(key)
  return out


def realism_gate_hard_fail_count(
  realism_gate_payload: Optional[Dict[str, Any]],
) -> int:
  return len(realism_gate_hard_fail_metric_keys(realism_gate_payload))


def build_realism_memo(
  *,
  realism_gate_payload: Optional[Dict[str, Any]] = None,
  schedule_sanity_payload: Optional[Dict[str, Any]] = None,
  warnings: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Build the realism_memo_json that gets persisted with the run.

  The legacy version walked the issue ledger; this version walks the
  realism gate's per-metric results plus the schedule-sanity payload
  (when it ran). The acceptance gate's
  realism_gate_provenance_recorded check looks for results with
  band_source — which the realism gate writes natively, so we just
  surface them as-is.
  """
  results = _realism_results_from(realism_gate_payload)
  warning_list: List[Dict[str, Any]] = list(warnings or [])
  if isinstance(realism_gate_payload, dict):
    rg_warnings = realism_gate_payload.get("warnings")
    if isinstance(rg_warnings, list):
      warning_list.extend(w for w in rg_warnings if isinstance(w, dict))
  return {
    "realism_gate": {
      "line_level": {
        "results": copy.deepcopy(results),
        "warnings": copy.deepcopy(warning_list),
      },
      "schedule_level": copy.deepcopy(schedule_sanity_payload or {}),
    },
    "results": copy.deepcopy(results),
    "warnings": copy.deepcopy(warning_list),
    "memo_version": "phase_8_no_issue_machinery",
  }


def build_persisted_realism_memo_payload(
  *,
  controller_resolution_state: Optional[Dict[str, Any]] = None,
  working_memo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """The legacy version reconciled the working memo with the controller
  state. With the controller state stripped of issue-ledger semantics,
  we just persist the working memo as-is. Callers still pass
  ``controller_resolution_state`` for back-compat; it's ignored."""
  _ = controller_resolution_state  # legacy compatibility, intentionally unused
  if isinstance(working_memo, dict) and working_memo:
    return copy.deepcopy(working_memo)
  return empty_realism_memo()


def build_controller_resolution_state(
  *,
  realism_gate_payload: Optional[Dict[str, Any]] = None,
  cascade_diagnostics: Optional[Dict[str, Any]] = None,
  planning_mode_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Replacement for ``_build_controller_resolution_state_from_issue_ledger``.

  Returns the dict shape downstream readers expect. The
  ``all_cleared`` field is True iff the realism gate has zero
  hard_fail violations. The ``remaining_issues`` field is populated
  from the realism gate's hard_fail metric keys (renamed: a "remaining
  issue" is now "a hard_fail metric the cascade hasn't resolved").
  """
  hard_fail_keys = realism_gate_hard_fail_metric_keys(realism_gate_payload)
  tolerated_codes: List[str] = []
  if isinstance(planning_mode_policy, dict):
    raw = planning_mode_policy.get("tolerated_issue_codes")
    if isinstance(raw, (list, tuple)):
      tolerated_codes = [str(c).strip().lower() for c in raw if str(c or "").strip()]
  remaining = [
    {"issue_code": k, "metric_key": k, "source": "realism_gate"}
    for k in hard_fail_keys
    if k.lower() not in tolerated_codes
  ]
  tier = None
  if isinstance(cascade_diagnostics, dict):
    tier = cascade_diagnostics.get("tier_landed")
  return {
    "all_cleared": len(remaining) == 0,
    "remaining_issues": remaining,
    "remaining_issue_count": len(remaining),
    "resolved_issues": [],
    "resolved_issue_count": 0,
    "tolerated_issues": [
      {"issue_code": code, "source": "planning_mode_policy"}
      for code in tolerated_codes
    ],
    "tolerated_issue_count": len(tolerated_codes),
    "iteration_pending_issues": [],
    "iteration_pending_issue_count": 0,
    "issue_status_records": [
      {
        "issue_code": k,
        "metric_key": k,
        "status": "remaining",
        "severity": "hard_fail",
        "source": "realism_gate",
      }
      for k in hard_fail_keys
      if k.lower() not in tolerated_codes
    ],
    "cascade_landed_tier": tier,
    "controller_resolution_state_version": "phase_8_no_issue_machinery",
  }


def build_resolution_summary(
  *,
  realism_gate_payload: Optional[Dict[str, Any]] = None,
  cascade_diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  hard_fail_keys = realism_gate_hard_fail_metric_keys(realism_gate_payload)
  return {
    "all_cleared": len(hard_fail_keys) == 0,
    "issue_summaries": [
      {"issue_code": k, "metric_key": k, "status": "hard_fail"}
      for k in hard_fail_keys
    ],
    "phase_issue_counts": {
      "convergence": len(hard_fail_keys),
      "cash_pass": 0,
      "finalize": 0,
    },
    "cascade_landed_tier": (
      cascade_diagnostics.get("tier_landed")
      if isinstance(cascade_diagnostics, dict)
      else None
    ),
    "summary_version": "phase_8_no_issue_machinery",
  }


def issue_status_records_from_state(
  state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  if not isinstance(state, dict):
    return []
  records = state.get("issue_status_records")
  if isinstance(records, list):
    return [r for r in records if isinstance(r, dict)]
  remaining = state.get("remaining_issues")
  if isinstance(remaining, list):
    out: List[Dict[str, Any]] = []
    for item in remaining:
      if isinstance(item, dict):
        out.append(
          {
            "issue_code": item.get("issue_code") or item.get("metric_key"),
            "metric_key": item.get("metric_key") or item.get("issue_code"),
            "status": "remaining",
            "severity": item.get("severity") or "hard_fail",
            "source": item.get("source") or "realism_gate",
          }
        )
    return out
  return []


def financial_story_issue_codes(
  controller_resolution_state: Optional[Dict[str, Any]],
) -> List[str]:
  out: List[str] = []
  if not isinstance(controller_resolution_state, dict):
    return out
  for r in controller_resolution_state.get("remaining_issues") or []:
    if not isinstance(r, dict):
      continue
    code = str(r.get("issue_code") or r.get("metric_key") or "").strip().lower()
    if code and code not in out:
      out.append(code)
  return out


def filter_cash_pass_owned_issue_records(
  records: Optional[Sequence[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  """Phase 8 — the legacy version filtered records by issue codes
  registered against phase=cash_pass. With the issue lookup table
  no longer consulted, we filter by realism gate metric_keys whose
  hard_fail check is cash-relevant. The conservative default is to
  keep records whose metric_key is in the small set of cash-flow /
  liquidity ratios the cash strategy operates on; everything else
  is convergence-owned.
  """
  if not records:
    return []
  cash_relevant_keys = {
    "current_ratio",
    "quick_ratio",
    "debt_to_equity",
    "debt_to_assets",
    "operating_cash_flow_margin",
  }
  out: List[Dict[str, Any]] = []
  for item in records:
    if not isinstance(item, dict):
      continue
    metric_key = str(item.get("metric_key") or item.get("issue_code") or "").strip().lower()
    if metric_key in cash_relevant_keys:
      out.append(item)
  return out
