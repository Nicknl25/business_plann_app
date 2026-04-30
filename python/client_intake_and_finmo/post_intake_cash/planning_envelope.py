import copy
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_cash_policy_errors,
  post_intake_cash_policy_for,
)

from .common import (
  buffer_components,
  canonical_cash_strategy_value,
  capital_structure_snapshot,
  cash_strategy_policy_guidance,
  debt_cash_support_multiplier,
  live_quarter_rows,
  safe_float,
  solved_lever_stub_value_map,
  solved_lever_value_map,
)


def build_cash_planning_envelope(
  *,
  selected_cash_strategy: Any,
  finmo_payload: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  lever_ids: Dict[str, str],
  default_buffer_months: float,
  months_per_quarter: float,
  preferred_debt_ratio: float,
  preferred_equity_ratio: float,
) -> Dict[str, Any]:
  """Build the pre-action cash envelope used to plan cash moves.

  This path may simulate prior surplus deployment because GPT has not applied
  cash moves yet. Post-action validation must not call this function.
  """
  rows_by_quarter = {
    int(safe_float(row.get("quarter_index")) or 0): row
    for row in live_quarter_rows(finmo_payload)
    if int(safe_float(row.get("quarter_index")) or 0) >= 1
  }
  live_quarters = sorted(rows_by_quarter.keys())
  lever_map = solved_lever_value_map(model_input_json)
  stub_value_map = solved_lever_stub_value_map(model_input_json)
  cash_policy_errors = post_intake_cash_policy_errors()
  if cash_policy_errors:
    raise RuntimeError(
      "post_intake_cash_policy_invalid: " + "; ".join(cash_policy_errors[:5])
    )

  debt_issuance_lever_id = str(lever_ids.get("debt_issuance") or "").strip()
  debt_repayment_lever_id = str(lever_ids.get("debt_repayment") or "").strip()
  owners_capital_lever_id = str(lever_ids.get("owners_capital") or "").strip()
  other_equity_lever_id = str(lever_ids.get("other_equity") or "").strip()
  distributions_lever_id = str(lever_ids.get("distributions") or "").strip()

  distributions_series = [int(round(float(safe_float(v) or 0.0))) for v in (lever_map.get(distributions_lever_id) or [])]
  debt_repayment_series = [int(round(float(safe_float(v) or 0.0))) for v in (lever_map.get(debt_repayment_lever_id) or [])]
  debt_issuance_series = [int(round(float(safe_float(v) or 0.0))) for v in (lever_map.get(debt_issuance_lever_id) or [])]
  owners_capital_series = [int(round(float(safe_float(v) or 0.0))) for v in (lever_map.get(owners_capital_lever_id) or [])]
  other_equity_series = [int(round(float(safe_float(v) or 0.0))) for v in (lever_map.get(other_equity_lever_id) or [])]

  violation_quarters: List[int] = []
  residual_gap_quarters: List[int] = []
  surplus_deployment_quarters: List[int] = []
  deterministic_updates: List[Dict[str, Any]] = []
  quarter_envelopes: List[Dict[str, Any]] = []
  previous_effective_other_equity = int(round(float(safe_float(stub_value_map.get(other_equity_lever_id)) or 0.0)))
  deterministic_update_keys: set[Tuple[str, int]] = set()
  cumulative_prior_surplus_deployment = 0

  for quarter_index in live_quarters:
    row = rows_by_quarter.get(quarter_index) or {}
    capital_structure = capital_structure_snapshot(
      row,
      preferred_debt_ratio=preferred_debt_ratio,
      preferred_equity_ratio=preferred_equity_ratio,
    )
    debt_to_equity = float(safe_float(capital_structure.get("debt_to_equity")) or 0.0)
    cash_policy = post_intake_cash_policy_for(
      cash_strategy=canonical_cash_strategy_value(selected_cash_strategy) or "balanced",
      debt_to_equity=debt_to_equity,
      required=True,
    ) or {}
    components = buffer_components(
      row,
      cash_floor_months=float(safe_float(cash_policy.get("cash_floor_months")) or default_buffer_months),
      cash_ceiling_months=float(safe_float(cash_policy.get("cash_ceiling_months")) or default_buffer_months),
      default_buffer_months=default_buffer_months,
      months_per_quarter=months_per_quarter,
    )
    buffer_required = int(components.get("cash_buffer_required") or 0)
    cash_ceiling = int(components.get("cash_ceiling") or buffer_required)
    ending_cash = int(round(float(safe_float(row.get("ending_cash")) or 0.0)))
    current_distribution = int(distributions_series[quarter_index - 1] if quarter_index - 1 < len(distributions_series) else 0)
    current_debt_repayment = int(debt_repayment_series[quarter_index - 1] if quarter_index - 1 < len(debt_repayment_series) else 0)
    current_debt_issuance = int(debt_issuance_series[quarter_index - 1] if quarter_index - 1 < len(debt_issuance_series) else 0)
    current_owners_capital = int(owners_capital_series[quarter_index - 1] if quarter_index - 1 < len(owners_capital_series) else 0)
    current_other_equity = int(other_equity_series[quarter_index - 1] if quarter_index - 1 < len(other_equity_series) else previous_effective_other_equity)
    support_multiplier = debt_cash_support_multiplier(
      lever_map=lever_map,
      quarter_index=quarter_index,
    )

    distribution_violation = bool(current_distribution > 0 and ending_cash <= buffer_required)
    buffer_violation = bool(ending_cash < buffer_required)
    hard_rule_distribution_removed = int(current_distribution if ending_cash <= buffer_required and current_distribution > 0 else 0)
    hard_rule_distribution_value = int(0 if hard_rule_distribution_removed > 0 else current_distribution)
    hard_rule_other_equity_value = int(
      previous_effective_other_equity
      if ending_cash <= buffer_required and current_other_equity < previous_effective_other_equity
      else current_other_equity
    )
    hard_rule_equity_payback_removed = int(max(0, hard_rule_other_equity_value - current_other_equity))
    effective_before_surplus = int(ending_cash + hard_rule_distribution_removed + hard_rule_equity_payback_removed)
    effective_ending_cash = int(effective_before_surplus - cumulative_prior_surplus_deployment)
    residual_funding_gap = int(max(0, buffer_required - effective_ending_cash))
    deploy_above_ceiling_required = bool(cash_policy.get("deploy_above_ceiling_required", True))
    deployable_surplus = int(
      max(0, effective_ending_cash - cash_ceiling)
      if deploy_above_ceiling_required and residual_funding_gap <= 0
      else 0
    )
    current_debt_level = int(round(float(safe_float(capital_structure.get("debt_level")) or 0.0)))
    hard_rule_actions: List[Dict[str, Any]] = []
    if hard_rule_distribution_removed > 0:
      if (distributions_lever_id, quarter_index) not in deterministic_update_keys:
        deterministic_update_keys.add((distributions_lever_id, quarter_index))
        deterministic_updates.append(
          {
            "lever_id": distributions_lever_id,
            "quarter_index": quarter_index,
            "exact_value": 0,
            "update_source": "python_hard_rule",
            "business_reason": "Distributions are not allowed when ending cash is at or below the required liquidity buffer.",
          }
        )
      hard_rule_actions.append(
        {
          "lever_id": distributions_lever_id,
          "quarter_index": quarter_index,
          "exact_value": 0,
          "reason": "forced_zero_distributions_below_buffer",
        }
      )
    if hard_rule_other_equity_value > current_other_equity:
      if (other_equity_lever_id, quarter_index) not in deterministic_update_keys:
        deterministic_update_keys.add((other_equity_lever_id, quarter_index))
        deterministic_updates.append(
          {
            "lever_id": other_equity_lever_id,
            "quarter_index": quarter_index,
            "exact_value": hard_rule_other_equity_value,
            "update_source": "python_hard_rule",
            "business_reason": "Equity payback is not allowed when ending cash is at or below the required liquidity buffer.",
          }
        )
      hard_rule_actions.append(
        {
          "lever_id": other_equity_lever_id,
          "quarter_index": quarter_index,
          "exact_value": hard_rule_other_equity_value,
          "reason": "forced_zero_equity_payback_below_buffer",
        }
      )

    if bool(buffer_violation or distribution_violation or hard_rule_actions):
      violation_quarters.append(quarter_index)
    if residual_funding_gap > 0:
      residual_gap_quarters.append(quarter_index)
    if deployable_surplus > 0:
      surplus_deployment_quarters.append(quarter_index)
      violation_quarters.append(quarter_index)
      cumulative_prior_surplus_deployment = int(cumulative_prior_surplus_deployment + deployable_surplus)

    quarter_envelopes.append(
      {
        "quarter_index": quarter_index,
        "date": row.get("date"),
        "ending_cash": ending_cash,
        "buffer": buffer_required,
        "cash_floor": buffer_required,
        "cash_ceiling": cash_ceiling,
        "cash_policy": copy.deepcopy(cash_policy),
        "monthly_opex": int(components.get("monthly_opex") or 0),
        "operating_expense_quarter": int(components.get("operating_expense_quarter") or 0),
        "deploy_above_ceiling_required": deploy_above_ceiling_required,
        "deployable_surplus_above_ceiling": deployable_surplus,
        "max_additional_distribution": deployable_surplus,
        "max_additional_debt_paydown": int(min(max(0, current_debt_level), deployable_surplus)),
        "distribution_current_value": current_distribution,
        "debt_repayment_current_value": current_debt_repayment,
        "debt_issuance_current_value": current_debt_issuance,
        "owners_capital_current_value": current_owners_capital,
        "other_equity_current_value": current_other_equity,
        "effective_other_equity_floor": hard_rule_other_equity_value,
        "equity_payback_removed": hard_rule_equity_payback_removed,
        "ending_cash_after_hard_rules": effective_ending_cash,
        "ending_cash_after_hard_rules_before_prior_surplus_deployment": effective_before_surplus,
        "prior_surplus_deployment_carryforward": int(cumulative_prior_surplus_deployment - deployable_surplus),
        "residual_funding_gap": residual_funding_gap,
        "buffer_violation": buffer_violation,
        "distribution_violation": distribution_violation,
        "hard_rule_actions": copy.deepcopy(hard_rule_actions),
        "capital_structure": copy.deepcopy(capital_structure),
        "soft_capital_structure_guidance": {
          "preferred_debt_ratio": round(float(preferred_debt_ratio), 2),
          "preferred_equity_ratio": round(float(preferred_equity_ratio), 2),
          "guidance_only": True,
          "priority_after_buffer_and_strategy": True,
        },
        "effective_current_values": {
          debt_repayment_lever_id: current_debt_repayment,
          debt_issuance_lever_id: current_debt_issuance,
          owners_capital_lever_id: current_owners_capital,
          other_equity_lever_id: hard_rule_other_equity_value,
          distributions_lever_id: hard_rule_distribution_value,
        },
        "debt_cash_support_multiplier": float(support_multiplier),
        "debt_cash_support_per_1000": int(round(float(support_multiplier) * 1000.0)),
        "cumulative_support_headroom": residual_funding_gap,
      }
    )
    previous_effective_other_equity = hard_rule_other_equity_value

  violation_quarters = []
  residual_gap_quarters = []
  surplus_deployment_quarters = []
  cumulative_prior_surplus_deployment = 0
  for idx, quarter_payload in enumerate(quarter_envelopes):
    effective_before_prior_deployment = int(round(float(safe_float(
      quarter_payload.get("ending_cash_after_hard_rules_before_prior_surplus_deployment")
    ) or safe_float(quarter_payload.get("ending_cash_after_hard_rules")) or 0.0)))
    effective_ending_cash = int(effective_before_prior_deployment - cumulative_prior_surplus_deployment)
    buffer_required = int(round(float(safe_float(quarter_payload.get("buffer")) or 0.0)))
    cash_ceiling = int(round(float(safe_float(quarter_payload.get("cash_ceiling")) or buffer_required)))
    residual_funding_gap = int(max(0, buffer_required - effective_ending_cash))
    future_buffer_headroom = min(
      int(round(float(safe_float(future_payload.get("ending_cash_after_hard_rules_before_prior_surplus_deployment")) or 0.0)))
      - cumulative_prior_surplus_deployment
      - int(round(float(safe_float(future_payload.get("buffer")) or 0.0)))
      for future_payload in quarter_envelopes[idx:]
      if isinstance(future_payload, dict)
    )
    deployable_surplus = int(
      max(0, min(max(0, effective_ending_cash - cash_ceiling), max(0, future_buffer_headroom)))
      if bool(quarter_payload.get("deploy_above_ceiling_required", True)) and residual_funding_gap <= 0
      else 0
    )
    if deployable_surplus > 0:
      surplus_deployment_quarters.append(int(quarter_payload.get("quarter_index") or 0))
      cumulative_prior_surplus_deployment = int(cumulative_prior_surplus_deployment + deployable_surplus)
    if bool(quarter_payload.get("buffer_violation")) or bool(quarter_payload.get("distribution_violation")) or quarter_payload.get("hard_rule_actions"):
      violation_quarters.append(int(quarter_payload.get("quarter_index") or 0))
    if residual_funding_gap > 0:
      residual_gap_quarters.append(int(quarter_payload.get("quarter_index") or 0))
      violation_quarters.append(int(quarter_payload.get("quarter_index") or 0))
    if deployable_surplus > 0:
      violation_quarters.append(int(quarter_payload.get("quarter_index") or 0))
    quarter_payload["ending_cash_after_hard_rules"] = int(effective_ending_cash)
    quarter_payload["prior_surplus_deployment_carryforward"] = int(cumulative_prior_surplus_deployment - deployable_surplus)
    quarter_payload["residual_funding_gap"] = int(residual_funding_gap)
    quarter_payload["buffer_violation"] = bool(residual_funding_gap > 0)
    quarter_payload["distribution_violation"] = bool(
      int(round(float(safe_float(quarter_payload.get("distribution_current_value")) or 0.0))) > 0
      and effective_ending_cash <= buffer_required
    )
    quarter_payload["deployable_surplus_above_ceiling"] = int(deployable_surplus)
    quarter_payload["max_additional_distribution"] = int(deployable_surplus)
    quarter_payload["max_additional_debt_paydown"] = int(
      min(
        int(round(float(safe_float((quarter_payload.get("capital_structure") or {}).get("debt_level")) or 0.0))),
        deployable_surplus,
      )
    )
    if isinstance(quarter_payload.get("supporting_metrics"), dict):
      quarter_payload["supporting_metrics"]["deployable_surplus_above_ceiling"] = int(deployable_surplus)

  rolling_support_headroom = 0
  for quarter_payload in reversed(quarter_envelopes):
    rolling_support_headroom = int(
      max(
        rolling_support_headroom,
        int(round(float(safe_float(quarter_payload.get("residual_funding_gap")) or 0.0))),
      )
    )
    quarter_payload["cumulative_support_headroom"] = int(rolling_support_headroom)

  return {
    "contract_version": "cash_strategy_violation_envelope_v1",
    "envelope_lifecycle": "planning_pre_action",
    "simulate_surplus_deployment_carryforward": True,
    "selected_cash_strategy": str(selected_cash_strategy or "").strip(),
    "strategy_policy": cash_strategy_policy_guidance(selected_cash_strategy),
    "has_violations": bool(violation_quarters),
    "violation_quarters": copy.deepcopy(sorted(set(violation_quarters))),
    "residual_gap_quarters": copy.deepcopy(residual_gap_quarters),
    "surplus_deployment_quarters": copy.deepcopy(sorted(set(surplus_deployment_quarters))),
    "allowed_review_quarters": copy.deepcopy(list(live_quarters)),
    "deterministic_hard_rule_updates": copy.deepcopy(deterministic_updates),
    "quarter_envelopes": copy.deepcopy(quarter_envelopes),
    "capital_structure_guidance": {
      "preferred_debt_ratio": round(float(preferred_debt_ratio), 2),
      "preferred_equity_ratio": round(float(preferred_equity_ratio), 2),
      "guidance_only": True,
      "priority_order": [
        "satisfy_liquidity_buffer",
        "respect_selected_cash_strategy",
        "consider_capital_structure_mix",
      ],
      "gpt_expectation": (
        "Use mixed debt and equity when it makes sense, avoid solving everything with debt, and avoid "
        "unnecessary equity dilution when one lever clearly dominates."
      ),
    },
    "validation_requirements": {
      "ending_cash_must_be_greater_than_or_equal_to_buffer": True,
      "no_distributions_when_cash_is_below_or_equal_to_buffer": True,
      "do_not_validate_on_debt_to_equity_ratio": True,
    },
  }
