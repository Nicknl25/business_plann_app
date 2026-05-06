"""Module 5 Task 5.6 — Python proposer for unified_convergence_verification.

Builds a deterministic per-issue verdict from the post-resolution
`unified_convergence_result.applied_updates` and the pre-resolution
`realism_memo_before_resolution.issue_packets`. The proposer does NOT
recompute finmo gaps — that machinery already lives upstream in the solver
and the realism module. Instead, the proposer uses what's already known:

  - `applied_updates`: which lever values changed and in which quarters
  - `issue_packet.affected_quarters`: which quarters the issue lives in
  - `issue_packet.candidate_lever_ids`: which levers were authorized to
    repair this issue
  - `issue_packet.repair_targets`: per-quarter target metric movements

For each issue, the proposer maps:
  - all candidate levers WERE applied across all affected quarters → "resolved"
  - some candidate levers WERE applied but not in every affected quarter
    → "partially_resolved"
  - no candidate levers WERE applied → "not_resolved"

GPT then critiques specific issue verdicts, e.g. flipping "partially_resolved"
to "resolved" when the consultant judges the residual gap acceptable. When
GPT fails, the proposer's verdicts stand as the safety floor — every
verdict has clear data provenance back to the convergence result.

Contract enum values (from `unified_convergence_verification` schema):
  - overall_assessment: all_resolved | partially_resolved | not_resolved
  - issue_results[].status: resolved | partially_resolved | not_resolved
  - issue_results[].remaining_issue_materiality: immaterial | material
  - issue_results[].remaining_problem_quarters: array of strings (e.g. "Q3")
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set


def _safe_int(value: Any) -> int:
  try:
    if value is None or value == "":
      return 0
    return int(round(float(value)))
  except Exception:
    return 0


def _clean(value: Any) -> str:
  return str(value or "").strip()


def _candidate_lever_ids(issue: Dict[str, Any]) -> List[str]:
  ids = issue.get("candidate_lever_ids") if isinstance(issue.get("candidate_lever_ids"), list) else []
  return [_clean(item) for item in ids if _clean(item)]


def _affected_quarters(issue: Dict[str, Any]) -> List[int]:
  for key in ("affected_quarters", "remaining_problem_quarters", "relevant_quarters"):
    value = issue.get(key)
    if isinstance(value, list):
      result = sorted({_safe_int(item) for item in value if _safe_int(item) >= 1})
      if result:
        return result
  return []


def _index_applied_updates(
  applied_updates: List[Dict[str, Any]],
) -> Dict[str, Set[int]]:
  """Index: lever_id → set of quarter_index touched by an applied update."""
  index: Dict[str, Set[int]] = {}
  for item in applied_updates or []:
    if not isinstance(item, dict):
      continue
    lever_id = _clean(item.get("lever_id"))
    if not lever_id:
      continue
    quarter_index = _safe_int(item.get("quarter_index"))
    if quarter_index <= 0:
      # Some applied_updates use timing_start_q/timing_end_q instead.
      start_q = _safe_int(item.get("timing_start_q"))
      end_q = _safe_int(item.get("timing_end_q")) or start_q
      if start_q >= 1:
        index.setdefault(lever_id, set()).update(range(start_q, max(start_q, end_q) + 1))
        continue
      continue
    index.setdefault(lever_id, set()).add(quarter_index)
  return index


def _verdict_for_issue(
  *,
  issue: Dict[str, Any],
  applied_index: Dict[str, Set[int]],
) -> Dict[str, Any]:
  candidate_levers = _candidate_lever_ids(issue)
  affected_quarters = _affected_quarters(issue)
  if not candidate_levers or not affected_quarters:
    return {
      "status": "not_resolved",
      "remaining_problem_quarters": affected_quarters,
      "next_required_lever_ids": candidate_levers,
      "applied_lever_count": 0,
      "remaining_quarter_count": len(affected_quarters),
      "rationale": (
        "Issue lacks candidate levers or affected quarters in convergence packet; "
        "deterministic verdict cannot be derived from applied_updates alone."
      ),
    }
  applied_quarters_for_issue: Set[int] = set()
  applied_lever_ids_for_issue: Set[str] = set()
  for lever_id in candidate_levers:
    quarters = applied_index.get(lever_id) or set()
    if quarters:
      applied_lever_ids_for_issue.add(lever_id)
      applied_quarters_for_issue.update(quarters & set(affected_quarters))
  remaining_problem_quarters = sorted(set(affected_quarters) - applied_quarters_for_issue)
  next_required_lever_ids = [
    lever_id for lever_id in candidate_levers if lever_id not in applied_lever_ids_for_issue
  ]
  if not applied_lever_ids_for_issue:
    status = "not_resolved"
    rationale = (
      f"No candidate lever was touched in the convergence pass for issue affecting Q"
      f"{affected_quarters[0]}-Q{affected_quarters[-1]}; issue remains unresolved."
    )
  elif not remaining_problem_quarters:
    status = "resolved"
    rationale = (
      f"All {len(affected_quarters)} affected quarter(s) saw an applied update on a candidate lever; "
      "issue closure is plausible from the convergence result."
    )
  else:
    status = "partially_resolved"
    rationale = (
      f"{len(applied_quarters_for_issue)} of {len(affected_quarters)} affected quarter(s) saw an applied update; "
      f"{len(remaining_problem_quarters)} quarter(s) still need attention."
    )
  return {
    "status": status,
    "remaining_problem_quarters": remaining_problem_quarters,
    "next_required_lever_ids": next_required_lever_ids,
    "applied_lever_count": len(applied_lever_ids_for_issue),
    "remaining_quarter_count": len(remaining_problem_quarters),
    "rationale": rationale,
  }


def propose_realism_verification_payload(
  *,
  issue_packets: List[Dict[str, Any]],
  applied_updates: List[Dict[str, Any]],
  realism_memo_before_resolution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Build a deterministic unified_convergence_verification payload.

  Returns a payload conforming to the SQL contract shape:
    {
      overall_assessment: "all_resolved" | "partial_resolution" | "no_progress",
      executive_summary: str,
      issue_results: [
        {
          issue_code, status, remaining_issue_materiality,
          remaining_issue_severity_score, verification_reason,
          remaining_problem_quarters, next_required_lever_ids,
          observed_improvement_summary
        },
        ...
      ]
    }

  Statuses (per `unified_convergence_verification` contract):
    - "resolved": every affected quarter saw an applied update on a candidate lever
    - "partially_resolved": some applied updates landed OR no candidate levers exist
    - "not_resolved": no candidate lever was touched
  """
  issue_packets_safe = [item for item in (issue_packets or []) if isinstance(item, dict)]
  applied_index = _index_applied_updates(applied_updates or [])
  issue_results: List[Dict[str, Any]] = []
  per_status_counts: Dict[str, int] = {"resolved": 0, "partially_resolved": 0, "not_resolved": 0}
  for issue in issue_packets_safe:
    verdict = _verdict_for_issue(issue=issue, applied_index=applied_index)
    pre_severity_score = _safe_int(issue.get("remaining_issue_severity_score")) or _safe_int(issue.get("impact_weight"))
    status = verdict["status"]
    per_status_counts[status] = per_status_counts.get(status, 0) + 1
    # Contract enum is strict: only "immaterial" or "material".
    # A resolved issue is immaterial; anything else carries forward as material.
    if status == "resolved":
      remaining_severity_score = 0
      remaining_materiality = "immaterial"
      observed_improvement_summary = (
        "Convergence pass applied lever updates across all affected quarters; "
        "issue gap is plausibly closed."
      )
    elif status == "partially_resolved":
      remaining_severity_score = max(1, min(100, int(round(pre_severity_score * 0.5)))) if pre_severity_score else 25
      remaining_materiality = "material"
      observed_improvement_summary = (
        f"Partial coverage: {verdict['applied_lever_count']} candidate lever(s) used; "
        f"{verdict['remaining_quarter_count']} quarter(s) still uncovered."
      )
    else:  # not_resolved
      remaining_severity_score = max(1, min(100, pre_severity_score or 50))
      remaining_materiality = "material"
      observed_improvement_summary = (
        "No applied update touched any candidate lever; original gap stands."
      )
    issue_results.append(
      {
        "issue_code": _clean(issue.get("issue_code")),
        "status": status,
        "remaining_issue_materiality": remaining_materiality,
        "remaining_issue_severity_score": int(remaining_severity_score),
        "verification_reason": verdict["rationale"],
        # Contract requires array of strings; format as "Q<n>".
        "remaining_problem_quarters": [f"Q{q}" for q in verdict["remaining_problem_quarters"]],
        "next_required_lever_ids": list(verdict["next_required_lever_ids"]),
        "observed_improvement_summary": observed_improvement_summary,
      }
    )
  total_count = len(issue_results)
  resolved_count = per_status_counts.get("resolved", 0)
  partially_count = per_status_counts.get("partially_resolved", 0)
  not_resolved_count = per_status_counts.get("not_resolved", 0)
  if total_count == 0:
    # Contract requires minItems=1; emit a single synthetic "no_issues" entry.
    overall_assessment = "all_resolved"
    executive_summary = "No issue packets were produced by the convergence pipeline; nothing to verify."
    issue_results = [
      {
        "issue_code": "no_open_issues",
        "status": "resolved",
        "remaining_issue_materiality": "immaterial",
        "remaining_issue_severity_score": 0,
        "verification_reason": "Convergence pipeline produced no open issues to verify.",
        "remaining_problem_quarters": [],
        "next_required_lever_ids": [],
        "observed_improvement_summary": "No issues required verification.",
      }
    ]
  elif not_resolved_count == 0 and partially_count == 0:
    overall_assessment = "all_resolved"
    executive_summary = (
      f"All {total_count} issue(s) saw applied updates across every affected quarter; "
      "convergence pass closed every authorized gap."
    )
  elif resolved_count == 0 and partially_count == 0:
    overall_assessment = "not_resolved"
    executive_summary = (
      f"No applied updates landed on any of the {total_count} issue(s); "
      "convergence pass made no measurable progress."
    )
  else:
    overall_assessment = "partially_resolved"
    executive_summary = (
      f"{resolved_count} of {total_count} issue(s) plausibly resolved; "
      f"{partially_count} partially_resolved; {not_resolved_count} not_resolved. Review residual quarters."
    )
  pre_status = _clean((realism_memo_before_resolution or {}).get("status"))
  return {
    "overall_assessment": overall_assessment,
    "executive_summary": executive_summary,
    "issue_results": issue_results,
    "_proposer_diagnostics": {
      "per_status_counts": per_status_counts,
      "applied_lever_quarter_count": sum(len(quarters) for quarters in applied_index.values()),
      "applied_lever_id_count": len(applied_index),
      "issue_packet_count": total_count,
      "pre_resolution_status": pre_status,
    },
  }


__all__ = [
  "propose_realism_verification_payload",
]
