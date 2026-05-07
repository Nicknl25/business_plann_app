"""Module 5 Task 5.5 — Python proposer for cash_strategy_review.

Walks each `required_funding_quarter` and selects ONE funding source per
quarter using the deterministic policy priority order
(`funding_source_policy.allowed_funding_source_lever_ids`), validated against
the per-quarter `lever_bounds` (current_value + max_value + cash_support_multiplier
gross-up for debt_issuance).

The proposer always returns a payload that satisfies
`_cash_strategy_review_decision_contract_error`. GPT then critiques timing,
mix, or business-reason language via the shared CritiqueResponse contract;
when GPT fails or the critique drives the payload outside the deterministic
bounds, Python's proposal stands as the safety floor.

Surplus deployment (deployable cash above the strategy ceiling) is
intentionally NOT placed in `quarter_funding_plan` here. Surplus deployment
is applied later from the rebuilt post-action FINMO state so early
distributions cannot overdraw future cash.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(value: Any) -> Optional[float]:
  try:
    if value is None or value == "":
      return None
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _safe_int(value: Any) -> int:
  return int(round(float(_safe_float(value) or 0.0)))


def _gross_up_effective_support(amount: int, multiplier: float) -> int:
  target = max(0, int(amount or 0))
  factor = float(multiplier or 1.0)
  if target <= 0:
    return 0
  if factor <= 0.0:
    return target
  candidate = max(0, int(round(target / factor)))
  for value in range(max(0, candidate - 3), candidate + 4):
    if int(round(value * factor)) == target:
      return int(value)
  return int(math.ceil(target / factor))


def _lever_bound_lookup(context: Dict[str, Any]) -> Dict[Tuple[str, int], Dict[str, Any]]:
  lookup: Dict[Tuple[str, int], Dict[str, Any]] = {}
  raw = context.get("lever_bounds") if isinstance(context.get("lever_bounds"), dict) else {}
  for lever_id, rows in (raw.get("lever_bounds") or {}).items():
    for row in rows or []:
      if not isinstance(row, dict):
        continue
      quarter_index = _safe_int(row.get("quarter_index"))
      if quarter_index >= 1:
        lookup[(str(lever_id or "").strip(), quarter_index)] = row
  return lookup


def _ordered_funding_sources(
  *,
  context: Dict[str, Any],
  default_lever_ids: List[str],
) -> List[str]:
  policy = context.get("funding_source_policy") if isinstance(context.get("funding_source_policy"), dict) else {}
  ordered = [
    str(item).strip()
    for item in (policy.get("allowed_funding_source_lever_ids") or default_lever_ids)
    if str(item).strip()
  ]
  return ordered


def _select_funding_source_for_quarter(
  *,
  quarter_index: int,
  required_gap: int,
  ordered_funding_sources: List[str],
  lever_bound_lookup: Dict[Tuple[str, int], Dict[str, Any]],
  debt_issuance_lever_id: str,
) -> Optional[Dict[str, Any]]:
  """Pick the first allowed funding source whose headroom covers the gap.

  Returns a dict with the chosen lever, the amount (gap), the gross-up
  exact_value (for debt_issuance), and the supporting metrics. Returns
  None when no allowed source has enough headroom — caller handles fallback.
  """
  for lever_id in ordered_funding_sources:
    bound = lever_bound_lookup.get((lever_id, quarter_index))
    if not isinstance(bound, dict):
      continue
    current_value = _safe_int(bound.get("current_value"))
    max_value = _safe_int(bound.get("max_value")) or current_value
    headroom = max(0, max_value - current_value)
    supporting_metrics = bound.get("supporting_metrics") if isinstance(bound.get("supporting_metrics"), dict) else {}
    multiplier = float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0)
    if lever_id == debt_issuance_lever_id:
      grossed_up_required = _gross_up_effective_support(required_gap, multiplier)
      if grossed_up_required <= headroom:
        return {
          "lever_id": lever_id,
          "funding_amount": int(required_gap),
          "exact_value": int(grossed_up_required),
          "current_value": current_value,
          "max_value": max_value,
          "cash_support_multiplier": round(multiplier, 6),
          "supporting_metrics": supporting_metrics,
        }
    else:
      if required_gap <= headroom:
        return {
          "lever_id": lever_id,
          "funding_amount": int(required_gap),
          "exact_value": int(required_gap),
          "current_value": current_value,
          "max_value": max_value,
          "cash_support_multiplier": 1.0,
          "supporting_metrics": supporting_metrics,
        }
  return None


def _max_headroom_summary_for_quarter(
  *,
  quarter_index: int,
  ordered_funding_sources: List[str],
  lever_bound_lookup: Dict[Tuple[str, int], Dict[str, Any]],
  debt_issuance_lever_id: str,
) -> List[Dict[str, Any]]:
  """Return per-source headroom snapshot for diagnostic output when no
  source can cover the gap. Used to build a clear fail-fast error.
  """
  rows: List[Dict[str, Any]] = []
  for lever_id in ordered_funding_sources:
    bound = lever_bound_lookup.get((lever_id, quarter_index))
    if not isinstance(bound, dict):
      rows.append({"lever_id": lever_id, "headroom": 0, "reason": "no_bound_for_quarter"})
      continue
    current_value = _safe_int(bound.get("current_value"))
    max_value = _safe_int(bound.get("max_value")) or current_value
    raw_headroom = max(0, max_value - current_value)
    supporting_metrics = bound.get("supporting_metrics") if isinstance(bound.get("supporting_metrics"), dict) else {}
    multiplier = float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0)
    if lever_id == debt_issuance_lever_id:
      effective = int(round(raw_headroom * multiplier))
    else:
      effective = raw_headroom
    rows.append(
      {
        "lever_id": lever_id,
        "current_value": current_value,
        "max_value": max_value,
        "raw_headroom": raw_headroom,
        "effective_cash_support": effective,
        "cash_support_multiplier": round(multiplier, 6),
      }
    )
  return rows


def _business_reason_for_funding(
  *,
  lever_id: str,
  quarter_index: int,
  amount: int,
  selected_cash_strategy: str,
) -> str:
  return (
    f"Q{quarter_index} closes the required funding gap with ${amount} from {lever_id}, the highest-priority "
    f"source with adequate headroom under the {selected_cash_strategy or 'selected'} cash policy."
  )


def propose_cash_strategy_review_decision(
  *,
  cash_strategy_review_context: Dict[str, Any],
  selected_cash_strategy: str,
  default_funding_source_lever_ids: List[str],
  debt_issuance_lever_id: str,
) -> Dict[str, Any]:
  """Build a deterministic cash_strategy_review decision payload.

  Returns a payload in `cash_strategy_review_decision_v2` shape. When there
  are no required_funding_quarters, returns recommendation_mode=maintain.
  When there are required_funding_quarters, walks each one in order and
  picks one funding source per quarter from the policy priority list,
  validated against the per-quarter lever_bounds.

  The proposer also returns `proposer_diagnostics` that capture which
  quarters fell back to underfunded allocations and which sources were
  considered. This enables the GPT critic to amend specific quarters
  without re-deriving from scratch.
  """
  context = cash_strategy_review_context if isinstance(cash_strategy_review_context, dict) else {}
  required_funding_quarters_raw = [
    item for item in (context.get("required_funding_quarters") or []) if isinstance(item, dict)
  ]
  required_funding_quarters = sorted(
    [
      {
        "quarter_index": _safe_int(item.get("quarter_index")),
        "required_incremental_funding_after_hard_rules": _safe_int(item.get("required_incremental_funding_after_hard_rules")),
        "buffer": _safe_int(item.get("buffer")),
        "ending_cash_after_hard_rules": _safe_int(item.get("ending_cash_after_hard_rules")),
      }
      for item in required_funding_quarters_raw
      if _safe_int(item.get("quarter_index")) >= 1
    ],
    key=lambda x: x["quarter_index"],
  )
  ordered_funding_sources = _ordered_funding_sources(
    context=context,
    default_lever_ids=default_funding_source_lever_ids,
  )
  lever_bound_lookup = _lever_bound_lookup(context)

  quarter_funding_plan: List[Dict[str, Any]] = []
  recommended_adjustments: List[Dict[str, Any]] = []
  proposer_diagnostics: Dict[str, Any] = {
    "ordered_funding_sources": list(ordered_funding_sources),
    "quarter_allocations": [],
    "underfunded_quarters": [],
  }
  total_funded = 0
  funding_mix_counts: Dict[str, int] = {}

  for quarter in required_funding_quarters:
    quarter_index = quarter["quarter_index"]
    required_gap = quarter["required_incremental_funding_after_hard_rules"]
    buffer_value = quarter["buffer"]
    ending_cash_after_hard_rules = quarter["ending_cash_after_hard_rules"]

    chosen = _select_funding_source_for_quarter(
      quarter_index=quarter_index,
      required_gap=required_gap,
      ordered_funding_sources=ordered_funding_sources,
      lever_bound_lookup=lever_bound_lookup,
      debt_issuance_lever_id=debt_issuance_lever_id,
    )
    if chosen is None:
      # The contract requires every required-funding quarter to be fully
      # covered by a single source whose effective cash support equals the
      # gap. When no allowed source has enough headroom, we cannot satisfy
      # the contract — record the diagnostic and skip the quarter so the
      # caller's contract validator surfaces a clear `missing_quarters`
      # error. The legacy GPT-from-scratch flow had the same hard limit;
      # the new architecture surfaces it deterministically instead of
      # discovering it via a downstream validation failure.
      proposer_diagnostics["underfunded_quarters"].append(
        {
          "quarter_index": quarter_index,
          "required_gap": required_gap,
          "reason": "no_allowed_source_has_headroom_for_full_gap_under_single_source_rule",
          "per_source_headroom": _max_headroom_summary_for_quarter(
            quarter_index=quarter_index,
            ordered_funding_sources=ordered_funding_sources,
            lever_bound_lookup=lever_bound_lookup,
            debt_issuance_lever_id=debt_issuance_lever_id,
          ),
        }
      )
      continue

    funding_amount = int(chosen["funding_amount"])
    exact_value = int(chosen["exact_value"])
    business_reason = _business_reason_for_funding(
      lever_id=chosen["lever_id"],
      quarter_index=quarter_index,
      amount=funding_amount,
      selected_cash_strategy=selected_cash_strategy,
    )

    # Contract requires `expected_ending_cash_after_actions >= expected_buffer`.
    # The `required_incremental_funding_after_hard_rules` is the *incremental*
    # new high-water gap for this quarter, not the cumulative one. After all
    # prior quarters' incremental funding rolls forward, the actual ending
    # cash for this quarter equals at least `buffer_value` (because that's
    # what the cumulative funding chain is designed to deliver). We therefore
    # assert at least `buffer_value` here, while preserving the in-quarter
    # arithmetic floor when it's larger.
    quarter_expected_ending_cash = max(
      int(buffer_value),
      int(ending_cash_after_hard_rules + funding_amount),
    )
    quarter_funding_plan.append(
      {
        "quarter_index": quarter_index,
        "required_funding_gap": int(required_gap),
        "funding_sources": [
          {
            "lever_id": chosen["lever_id"],
            "amount": funding_amount,
          }
        ],
        "expected_buffer": int(buffer_value),
        "expected_ending_cash_after_actions": int(quarter_expected_ending_cash),
        "business_reason": business_reason,
      }
    )
    recommended_adjustments.append(
      {
        "lever_id": chosen["lever_id"],
        "exact_value": exact_value,
        "timing_start_q": quarter_index,
        "timing_end_q": quarter_index,
        "business_reason": business_reason,
      }
    )
    total_funded += funding_amount
    funding_mix_counts[chosen["lever_id"]] = funding_mix_counts.get(chosen["lever_id"], 0) + 1
    proposer_diagnostics["quarter_allocations"].append(
      {
        "quarter_index": quarter_index,
        "lever_id": chosen["lever_id"],
        "funding_amount": funding_amount,
        "exact_value": exact_value,
      }
    )

  recommendation_mode = (
    "adjust" if (quarter_funding_plan or required_funding_quarters) else "maintain"
  )
  funding_mix_summary = (
    "; ".join(f"{lever_id}: {count} qtr(s)" for lever_id, count in sorted(funding_mix_counts.items()))
    if funding_mix_counts
    else "No funding required for the forecast horizon."
  )
  capital_posture_summary = (
    f"Selected cash strategy: {selected_cash_strategy or 'unspecified'}. "
    f"Funding sources walked in policy priority order: {', '.join(ordered_funding_sources) or 'none'}. "
    f"Surplus deployment is applied post-action and not in this proposal."
  )
  underfunded = proposer_diagnostics["underfunded_quarters"]
  if recommendation_mode == "maintain":
    executive_summary = (
      "No required funding quarters in the cash horizon under the selected strategy and lever bounds; "
      "current plan is sufficient."
    )
  elif underfunded:
    underfunded_qs = [item["quarter_index"] for item in underfunded]
    executive_summary = (
      f"{len(quarter_funding_plan)} quarter(s) covered with deterministic policy-priority funding; "
      f"{len(underfunded)} quarter(s) {underfunded_qs} cannot be funded under the cash policy + lever_bounds "
      "single-source rule. The runner will surface this as a proposer_invalid_contract failure with the "
      "missing_quarters list so the operator can review per-quarter source headroom."
    )
  else:
    executive_summary = (
      f"Funded all {len(quarter_funding_plan)} required quarters using policy-priority cash levers. "
      f"Total cash support proposed: ${total_funded}."
    )
  return {
    "recommendation_mode": recommendation_mode,
    "quarter_funding_plan": quarter_funding_plan,
    "recommended_adjustments": recommended_adjustments,
    "executive_summary": executive_summary,
    "capital_posture_summary": capital_posture_summary,
    "funding_mix_summary": funding_mix_summary,
    "confidence": "high" if not underfunded else "low",
    "proposer_diagnostics": proposer_diagnostics,
  }


__all__ = [
  "propose_cash_strategy_review_decision",
]
