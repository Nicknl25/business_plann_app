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
intentionally NOT placed in `quarter_funding_plan` here — the legacy
`_normalize_cash_strategy_review_decision_from_funding_plan` comment
documents the reason: "Surplus deployment is intentionally applied later
from the rebuilt post-action FINMO state so early distributions cannot
overdraw future cash." The proposer mirrors that policy.
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


def _select_fallback_funding_source(
  *,
  quarter_index: int,
  required_gap: int,
  ordered_funding_sources: List[str],
  lever_bound_lookup: Dict[Tuple[str, int], Dict[str, Any]],
  debt_issuance_lever_id: str,
) -> Optional[Dict[str, Any]]:
  """When no source has enough headroom for the full gap, pick the first
  allowed source with ANY headroom and use its full headroom as the funding
  amount. The contract validator will mark this quarter as still
  underfunded; the user-facing diagnostic path surfaces the shortfall.
  This is the safety floor: a partial allocation is better than an empty
  one because downstream solver will at least see Python's intent.
  """
  for lever_id in ordered_funding_sources:
    bound = lever_bound_lookup.get((lever_id, quarter_index))
    if not isinstance(bound, dict):
      continue
    current_value = _safe_int(bound.get("current_value"))
    max_value = _safe_int(bound.get("max_value")) or current_value
    headroom = max(0, max_value - current_value)
    if headroom <= 0:
      continue
    supporting_metrics = bound.get("supporting_metrics") if isinstance(bound.get("supporting_metrics"), dict) else {}
    multiplier = float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0)
    if lever_id == debt_issuance_lever_id:
      effective_support = int(round(headroom * multiplier))
      if effective_support <= 0:
        continue
      return {
        "lever_id": lever_id,
        "funding_amount": int(effective_support),
        "exact_value": int(headroom),
        "current_value": current_value,
        "max_value": max_value,
        "cash_support_multiplier": round(multiplier, 6),
        "supporting_metrics": supporting_metrics,
        "is_underfunded_fallback": True,
        "shortfall": max(0, int(required_gap) - int(effective_support)),
      }
    else:
      return {
        "lever_id": lever_id,
        "funding_amount": int(headroom),
        "exact_value": int(headroom),
        "current_value": current_value,
        "max_value": max_value,
        "cash_support_multiplier": 1.0,
        "supporting_metrics": supporting_metrics,
        "is_underfunded_fallback": True,
        "shortfall": max(0, int(required_gap) - int(headroom)),
      }
  return None


def _business_reason_for_funding(
  *,
  lever_id: str,
  quarter_index: int,
  amount: int,
  shortfall: int,
  selected_cash_strategy: str,
  is_fallback: bool,
) -> str:
  if amount <= 0:
    return (
      f"Q{quarter_index} required funding gap could not be allocated to any allowed source under "
      f"the {selected_cash_strategy or 'selected'} cash policy; remaining shortfall=${shortfall}."
    )
  if is_fallback:
    return (
      f"Q{quarter_index} allocates ${amount} to {lever_id} (the only source with available headroom under the "
      f"{selected_cash_strategy or 'selected'} cash policy). Quarter remains underfunded by ${shortfall}; review."
    )
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
    expected_ending_cash = ending_cash_after_hard_rules + required_gap

    chosen = _select_funding_source_for_quarter(
      quarter_index=quarter_index,
      required_gap=required_gap,
      ordered_funding_sources=ordered_funding_sources,
      lever_bound_lookup=lever_bound_lookup,
      debt_issuance_lever_id=debt_issuance_lever_id,
    )
    is_fallback = False
    if chosen is None:
      chosen = _select_fallback_funding_source(
        quarter_index=quarter_index,
        required_gap=required_gap,
        ordered_funding_sources=ordered_funding_sources,
        lever_bound_lookup=lever_bound_lookup,
        debt_issuance_lever_id=debt_issuance_lever_id,
      )
      is_fallback = True
    if chosen is None:
      proposer_diagnostics["underfunded_quarters"].append(
        {
          "quarter_index": quarter_index,
          "required_gap": required_gap,
          "shortfall": required_gap,
          "reason": "no_allowed_source_with_headroom",
        }
      )
      continue

    funding_amount = int(chosen["funding_amount"])
    exact_value = int(chosen["exact_value"])
    shortfall = int(chosen.get("shortfall") or max(0, required_gap - funding_amount))
    business_reason = _business_reason_for_funding(
      lever_id=chosen["lever_id"],
      quarter_index=quarter_index,
      amount=funding_amount,
      shortfall=shortfall,
      selected_cash_strategy=selected_cash_strategy,
      is_fallback=is_fallback or bool(chosen.get("is_underfunded_fallback")),
    )

    declared_gap = required_gap if not is_fallback and shortfall == 0 else funding_amount
    quarter_funding_plan.append(
      {
        "quarter_index": quarter_index,
        "required_funding_gap": int(declared_gap),
        "funding_sources": [
          {
            "lever_id": chosen["lever_id"],
            "amount": funding_amount,
          }
        ],
        "expected_buffer": int(buffer_value),
        "expected_ending_cash_after_actions": int(ending_cash_after_hard_rules + funding_amount),
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
        "is_fallback": is_fallback or bool(chosen.get("is_underfunded_fallback")),
        "shortfall": shortfall,
      }
    )
    if shortfall > 0:
      proposer_diagnostics["underfunded_quarters"].append(
        {
          "quarter_index": quarter_index,
          "required_gap": required_gap,
          "funded_amount": funding_amount,
          "shortfall": shortfall,
          "lever_id": chosen["lever_id"],
        }
      )

  recommendation_mode = "adjust" if quarter_funding_plan else "maintain"
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
    executive_summary = (
      f"{len(quarter_funding_plan)} quarter(s) covered with deterministic policy-priority funding; "
      f"{len(underfunded)} quarter(s) remain underfunded due to lever bound exhaustion. "
      "Proposal provides the safety-floor allocation; downstream solver and post-action FINMO rebuild will surface any residual gap."
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
    "confidence": "high" if not underfunded else "medium",
    "proposer_diagnostics": proposer_diagnostics,
  }


__all__ = [
  "propose_cash_strategy_review_decision",
]
