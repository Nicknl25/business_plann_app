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


def _allocate_funding_sources_for_quarter(
  *,
  quarter_index: int,
  required_gap: int,
  ordered_funding_sources: List[str],
  lever_bound_lookup: Dict[Tuple[str, int], Dict[str, Any]],
  debt_issuance_lever_id: str,
  source_remaining_caps: Optional[Dict[str, float]] = None,
  preferred_debt_share: Optional[float] = None,
  owner_capital_lever_id: str = "",
  debt_ceiling_active: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
  """FUNDING WATERFALL — fill the quarter's gap from the ordered sources,
  each up to its headroom (and cumulative capacity cap), remainder to the
  next source. Pre-waterfall the proposer demanded a SINGLE source cover
  the FULL gap, which silently excluded owner capital from any quarter
  whose gap exceeded the owner's capacity (Meridian's Q1 $1.46M gap vs
  $650k stated owner capacity -> an all-debt Q1 whose interest sank the
  NI ramp while the owner's capital dribbled into later small gaps).

  Returns ``(allocations, unfunded_remainder)``. Each allocation carries
  the lever, the cash-support amount, and the exact_value the executor
  writes (grossed up for debt). ``source_remaining_caps`` is decremented
  in place for capped sources (the owner-capacity cap).
  """
  caps = source_remaining_caps if isinstance(source_remaining_caps, dict) else {}
  allocations_by_lever: Dict[str, Dict[str, Any]] = {}
  ordered_seen: List[str] = []
  remaining = int(max(0, required_gap))

  def _try_take(lever_id: str, want: int) -> int:
    """Take up to ``want`` cash support from a source; returns the take.
    Merges repeat takes on the same lever (the split's spillover pass)
    and re-derives the debt gross-up on the MERGED amount so the
    exact_value round-trip always holds."""
    if want <= 0:
      return 0
    bound = lever_bound_lookup.get((lever_id, quarter_index))
    if not isinstance(bound, dict):
      return 0
    current_value = _safe_int(bound.get("current_value"))
    max_value = _safe_int(bound.get("max_value")) or current_value
    headroom = max(0, max_value - current_value)
    if lever_id in caps:
      headroom = int(min(headroom, max(0.0, float(caps[lever_id]))))
    prior = allocations_by_lever.get(lever_id)
    prior_amount = int(prior.get("funding_amount")) if isinstance(prior, dict) else 0
    supporting_metrics = bound.get("supporting_metrics") if isinstance(bound.get("supporting_metrics"), dict) else {}
    multiplier = float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0)
    if lever_id == debt_issuance_lever_id:
      total = min(prior_amount + want, int(round(headroom * multiplier)))
      exact = _gross_up_effective_support(total, multiplier)
      _guard = 0
      while total > prior_amount and exact > headroom and _guard < 8:
        total = max(prior_amount, total - max(1, exact - headroom))
        exact = _gross_up_effective_support(total, multiplier)
        _guard += 1
      take = int(max(0, total - prior_amount))
      if take < 1 or exact > headroom:
        return 0
      _prior_exact = int(prior.get("exact_value")) if isinstance(prior, dict) else 0
      allocations_by_lever[lever_id] = {
        "lever_id": lever_id,
        "funding_amount": int(total),
        "exact_value": int(exact),
        "current_value": current_value,
        "max_value": max_value,
        "cash_support_multiplier": round(multiplier, 6),
        "supporting_metrics": supporting_metrics,
      }
      # The debt serviceability ceiling caps cumulative PRINCIPAL
      # (exact_value, grossed up), so decrement by the exact delta.
      if lever_id in caps:
        caps[lever_id] = max(0.0, float(caps[lever_id]) - float(max(0, exact - _prior_exact)))
    else:
      take = int(min(want, max(0, headroom - prior_amount)))
      if take < 1:
        return 0
      total = prior_amount + take
      allocations_by_lever[lever_id] = {
        "lever_id": lever_id,
        "funding_amount": int(total),
        "exact_value": int(total),
        "current_value": current_value,
        "max_value": max_value,
        "cash_support_multiplier": 1.0,
        "supporting_metrics": supporting_metrics,
      }
      if lever_id in caps:
        caps[lever_id] = max(0.0, float(caps[lever_id]) - float(take))
    if lever_id not in ordered_seen:
      ordered_seen.append(lever_id)
    return take

  # CLIENT FUNDING PREFERENCE 'both' — aim the blend at the chosen
  # debt/equity split (70/30, 50/50, 30/70): phase 1 caps each family
  # at its share of the gap; phase 2 spills any un-fillable remainder
  # across every source in order. A preference is NEVER a deal-breaker:
  # the split binds only where headroom and the owner-capacity cap make
  # it real. No preference -> the plain waterfall walk (byte-identical).
  if preferred_debt_share is not None:
    _share = min(1.0, max(0.0, float(preferred_debt_share)))
    debt_budget = int(round(remaining * _share))
    equity_budget = int(remaining - debt_budget)
    for lever_id in ordered_funding_sources:
      if remaining <= 0:
        break
      is_debt = lever_id == debt_issuance_lever_id
      budget = debt_budget if is_debt else equity_budget
      take = _try_take(lever_id, min(remaining, budget))
      remaining -= take
      if is_debt:
        debt_budget -= take
      else:
        equity_budget -= take
  for lever_id in ordered_funding_sources:
    if remaining <= 0:
      break
    remaining -= _try_take(lever_id, remaining)

  # DEBT-CEILING SUBSTITUTION (root #2): when the serviceability ceiling
  # stopped debt short of the quarter's need, OWNER EQUITY funds the
  # remainder — beyond its demonstrated-capacity cap (the equity AMOUNT
  # is the client's business; the plan surfaces the number, it does not
  # judge it). The substitution never fails a business for carrying too
  # much debt: debt was simply the wrong instrument for the excess. The
  # per-quarter lever bound still applies (the executor contract);
  # anything truly unfundable stays an honest unfunded remainder.
  if (
    remaining > 0
    and debt_ceiling_active
    and owner_capital_lever_id
  ):
    _owner_prior = allocations_by_lever.get(owner_capital_lever_id)
    _owner_prior_amt = (
      int(_owner_prior.get("funding_amount")) if isinstance(_owner_prior, dict) else 0
    )
    _saved_owner_cap = caps.pop(owner_capital_lever_id, None)
    _sub_take = _try_take(owner_capital_lever_id, remaining)
    if _saved_owner_cap is not None:
      caps[owner_capital_lever_id] = _saved_owner_cap
    if _sub_take > 0:
      remaining -= _sub_take
      _owner_alloc = allocations_by_lever.get(owner_capital_lever_id)
      if isinstance(_owner_alloc, dict):
        _owner_alloc["debt_ceiling_substituted_amount"] = int(
          int(_owner_alloc.get("debt_ceiling_substituted_amount") or 0) + _sub_take
        )
        _owner_alloc["substitution_reason"] = (
          "debt stopped at its serviceability ceiling (judged believable "
          "margin at the 1.5x lender coverage floor); owner equity funds "
          "the remainder"
        )

  allocations = [allocations_by_lever[lid] for lid in ordered_seen if lid in allocations_by_lever]
  return allocations, int(max(0, remaining))


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
  # OWNER CAPACITY CAP — cumulative across the whole plan, from the
  # funding source policy (stated initial equity + cash on hand).
  _policy = context.get("funding_source_policy") if isinstance(context.get("funding_source_policy"), dict) else {}
  source_remaining_caps: Dict[str, float] = {}
  _owner_lever = str(_policy.get("owner_capital_lever_id") or "").strip()
  _owner_cap = _safe_float(_policy.get("owner_capital_cumulative_cap"))
  if _owner_lever and _owner_cap is not None:
    source_remaining_caps[_owner_lever] = max(0.0, float(_owner_cap))
  # DEBT SERVICEABILITY CEILING (root #2) — cumulative debt draws stop
  # at the principal whose interest the judged believable margin can
  # service at the lender coverage floor; the remainder substitutes to
  # owner equity (see the substitution pass in the allocator).
  _policy_debt_lever = str(_policy.get("debt_lever_id") or "").strip()
  _policy_debt_cap = _safe_float(_policy.get("debt_cumulative_cap"))
  if _policy_debt_lever and _policy_debt_cap is not None:
    source_remaining_caps[_policy_debt_lever] = max(0.0, float(_policy_debt_cap))
  # CLIENT FUNDING PREFERENCE 'both' — the chosen debt share steers each
  # quarter's blend (absent -> None -> plain waterfall, byte-identical).
  _pref_payload = _policy.get("client_funding_preference") if isinstance(_policy.get("client_funding_preference"), dict) else {}
  preferred_debt_share = (
    _safe_float(_pref_payload.get("debt_share"))
    if str(_pref_payload.get("preference") or "") == "both"
    else None
  )

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

    allocations, unfunded_remainder = _allocate_funding_sources_for_quarter(
      quarter_index=quarter_index,
      required_gap=required_gap,
      ordered_funding_sources=ordered_funding_sources,
      lever_bound_lookup=lever_bound_lookup,
      debt_issuance_lever_id=debt_issuance_lever_id,
      source_remaining_caps=source_remaining_caps,
      preferred_debt_share=preferred_debt_share,
      owner_capital_lever_id=_owner_lever,
      debt_ceiling_active=bool(_policy_debt_lever and _policy_debt_cap is not None),
    )
    _subs_amount = sum(
      int(a.get("debt_ceiling_substituted_amount") or 0) for a in allocations
    )
    if _subs_amount > 0:
      proposer_diagnostics.setdefault("debt_ceiling_substitutions", []).append(
        {"quarter_index": quarter_index, "equity_substituted_for_debt": int(_subs_amount)}
      )
    if not allocations or unfunded_remainder > 0:
      # The contract requires every required-funding quarter to be fully
      # covered (allocations must sum exactly to the gap). When even the
      # full waterfall cannot cover it, record the diagnostic and skip
      # the quarter so the caller's contract validator surfaces a clear
      # `missing_quarters` error.
      proposer_diagnostics["underfunded_quarters"].append(
        {
          "quarter_index": quarter_index,
          "required_gap": required_gap,
          "unfunded_remainder": int(unfunded_remainder),
          "reason": "waterfall_headroom_cannot_cover_full_gap",
          "per_source_headroom": _max_headroom_summary_for_quarter(
            quarter_index=quarter_index,
            ordered_funding_sources=ordered_funding_sources,
            lever_bound_lookup=lever_bound_lookup,
            debt_issuance_lever_id=debt_issuance_lever_id,
          ),
        }
      )
      continue

    funding_amount = int(sum(int(a["funding_amount"]) for a in allocations))
    business_reason = _business_reason_for_funding(
      lever_id=" + ".join(str(a["lever_id"]) for a in allocations),
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
            "lever_id": allocation["lever_id"],
            "amount": int(allocation["funding_amount"]),
          }
          for allocation in allocations
        ],
        "expected_buffer": int(buffer_value),
        "expected_ending_cash_after_actions": int(quarter_expected_ending_cash),
        "business_reason": business_reason,
      }
    )
    for allocation in allocations:
      recommended_adjustments.append(
        {
          "lever_id": allocation["lever_id"],
          "exact_value": int(allocation["exact_value"]),
          "timing_start_q": quarter_index,
          "timing_end_q": quarter_index,
          "business_reason": business_reason,
        }
      )
      funding_mix_counts[allocation["lever_id"]] = funding_mix_counts.get(allocation["lever_id"], 0) + 1
      proposer_diagnostics["quarter_allocations"].append(
        {
          "quarter_index": quarter_index,
          "lever_id": allocation["lever_id"],
          "funding_amount": int(allocation["funding_amount"]),
          "exact_value": int(allocation["exact_value"]),
        }
      )
    total_funded += funding_amount

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
