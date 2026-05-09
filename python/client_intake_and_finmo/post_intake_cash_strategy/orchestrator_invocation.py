"""Phase 9 Phase F — mode-based cash strategy.

Walks the FINMO quarter rows, applies the client-selected cash strategy
mode (preserve_cash / balanced / shareholder_return), and persists per-
quarter debt issuance, debt repayment, owners_capital, and distributions
to model_input. Industry-derived buffer + interest rate + loan term come
from the unified industry profile (Phase E).

Doctrine binding:
  - Cash pass MAY adjust: debt_issuance, debt_repayment, owners_capital,
    other_equity, distributions, minimum cash buffer, short_term_debt_pct
  - Cash pass MAY NOT adjust: revenue, COGS, payroll, G&A, marketing,
    R&D, lease, pricing, utilization, capacity, EBITDA target tolerances
  - Cash pass runs AFTER operating viability is established. If the
    operating model has no route to viability, the cascade fires the
    revenue_achievability / turnaround_recovery_q5_q11 families first;
    cash pass is the final funding pass.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


_DEFAULT_HORIZON = 20
_OPERATING_EXPENSE_FIELDS = (
  "payroll", "lease_rent", "marketing", "research_and_development",
  "general_and_administrative", "cost_of_goods_sold",
)
_DEFAULT_INTEREST_RATE = 0.09
_SURPLUS_THRESHOLD_MULTIPLIER_DEFAULT = 1.5

_MODE_DISTRIBUTION_FRACTION = {
  "preserve_cash": 0.0,
  "balanced": 0.30,
  "shareholder_return": 0.70,
}

# Phase 9 corrective: mode preference is now the ORDER of exploration
# WITHIN allowed sources, not a gate on what's allowed. The gate is
# _cash_strategy_funding_source_policy() (post_intake_cash/runner.py:1162),
# which excludes debt_issuance when chronic gaps + material drag exist
# and excludes other_equity when the situation doesn't justify outside
# investor capital. All three modes now include other_equity in their
# preference list so the smart policy can route to it when appropriate.
_MODE_FUNDING_LEVER_PREFERENCE_ORDER = {
  # preserve_cash: own equity first (lowest leverage drag), then outside
  # equity if chronic, then debt only as last bridge.
  "preserve_cash": ("owners_capital", "other_equity", "debt_issuance"),
  # balanced: debt for short bridges, then owner equity, then outside.
  "balanced": ("debt_issuance", "owners_capital", "other_equity"),
  # shareholder_return: same lever order as balanced; mode affects
  # distribution fraction not funding source.
  "shareholder_return": ("debt_issuance", "owners_capital", "other_equity"),
}


@dataclass
class CashQuarterDecision:
  quarter_index: int
  starting_cash: float
  required_buffer: float
  funding_gap: float
  surplus_above_threshold: float
  ending_cash_pre_action: float
  decisions: Dict[str, float] = field(default_factory=dict)
  notes: List[str] = field(default_factory=list)

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class CashStrategyResult:
  cash_strategy_mode: str
  buffer_months: float
  buffer_floor_months: float
  interest_rate: float
  loan_term_months: int
  per_quarter: List[CashQuarterDecision]
  total_debt_issued: float = 0.0
  total_distributions: float = 0.0
  total_owners_capital_added: float = 0.0
  total_other_equity_added: float = 0.0
  status: str = "completed"
  reason: Optional[str] = None
  applied_updates_count: int = 0
  funding_source_policy: Dict[str, Any] = field(default_factory=dict)
  effective_funding_priority: List[str] = field(default_factory=list)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "cash_strategy_mode": self.cash_strategy_mode,
      "buffer_months": self.buffer_months,
      "buffer_floor_months": self.buffer_floor_months,
      "interest_rate": self.interest_rate,
      "loan_term_months": self.loan_term_months,
      "per_quarter": [q.to_dict() for q in self.per_quarter],
      "total_debt_issued": self.total_debt_issued,
      "total_distributions": self.total_distributions,
      "total_owners_capital_added": self.total_owners_capital_added,
      "total_other_equity_added": self.total_other_equity_added,
      "status": self.status,
      "reason": self.reason,
      "applied_updates_count": self.applied_updates_count,
      "funding_source_policy": dict(self.funding_source_policy),
      "effective_funding_priority": list(self.effective_funding_priority),
    }


def _safe_float(value: Any) -> float:
  if value is None or value == "":
    return 0.0
  try:
    n = float(value)
  except Exception:
    return 0.0
  if n != n:
    return 0.0
  return n


def _normalize_cash_strategy_mode(adaptive_policy: Optional[Dict[str, Any]]) -> str:
  if not isinstance(adaptive_policy, dict):
    return "balanced"
  raw = (
    adaptive_policy.get("selected_cash_strategy")
    or adaptive_policy.get("cash_strategy")
    or "balanced"
  )
  norm = str(raw or "").strip().lower()
  if norm in ("conservative",):
    return "preserve_cash"
  if norm in ("aggressive",):
    return "shareholder_return"
  if norm in _MODE_FUNDING_LEVER_PREFERENCE_ORDER:
    return norm
  return "balanced"


def _quarter_row_lookup(finmo_json: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
  out: Dict[int, Dict[str, Any]] = {}
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      q = int(round(float(row.get("quarter_index"))))
    except Exception:
      continue
    if q >= 1:
      out[q] = row
  return out


def _quarter_operating_expense_base(row: Dict[str, Any]) -> float:
  total = 0.0
  for field_name in _OPERATING_EXPENSE_FIELDS:
    total += _safe_float(row.get(field_name))
  return max(total, 0.0)


def _resolve_lever_id(driver_key: str) -> str:
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_driver_target_single_lever_id_for_target_driver,
    )
    lever = post_intake_driver_target_single_lever_id_for_target_driver(driver_key)
    return str(lever or "").strip()
  except Exception:
    return ""


def _industry_profile_or_default(
  *,
  industry_profile: Optional[Dict[str, Any]],
  adaptive_policy: Optional[Dict[str, Any]],
) -> Tuple[float, float, float, int]:
  """Return (buffer_months, buffer_floor_months, interest_rate, loan_term_months)
  from the industry_profile dict; falls back to conservative defaults if
  the profile is missing.
  """
  if isinstance(industry_profile, dict) and industry_profile:
    base = _safe_float(industry_profile.get("cash_buffer_base_months")) or 1.5
    floor = _safe_float(industry_profile.get("cash_buffer_floor_months")) or 0.5
    rate = _safe_float(industry_profile.get("interest_rate")) or _DEFAULT_INTEREST_RATE
    term = int(industry_profile.get("loan_term_months") or 84)
  else:
    base, floor, rate, term = 1.5, 0.5, _DEFAULT_INTEREST_RATE, 84
  return base, floor, rate, term


def _cash_buffer_months_for_mode(
  *,
  industry_profile: Optional[Dict[str, Any]],
  cash_strategy_mode: str,
) -> float:
  if isinstance(industry_profile, dict):
    multipliers = industry_profile.get("cash_strategy_mode_multipliers") or {}
    multiplier = float(multipliers.get(cash_strategy_mode) or 1.0)
    base = _safe_float(industry_profile.get("cash_buffer_base_months")) or 1.5
    floor = _safe_float(industry_profile.get("cash_buffer_floor_months")) or 0.5
    return max(base * multiplier, floor)
  # Defaults if profile missing.
  return {"preserve_cash": 2.25, "balanced": 1.5, "shareholder_return": 1.05}.get(
    cash_strategy_mode, 1.5
  )


def run_mode_based_cash_strategy(
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  industry_profile: Optional[Dict[str, Any]] = None,
  adaptive_policy: Optional[Dict[str, Any]] = None,
  conn: Any = None,
  horizon: int = _DEFAULT_HORIZON,
  finmo_rebuild_callable: Optional[Any] = None,
) -> CashStrategyResult:
  """Phase 9 Phase F entry point.

  Replaces the Phase 8 minimal cash strategy (Q1 lump-sum dump) with a
  per-quarter mode-driven funding policy. Returns CashStrategyResult
  carrying the per-quarter decisions and totals; mutates ``model_input_json``
  in place via apply_exact_lever_updates_to_model_input().
  """
  cash_strategy_mode = _normalize_cash_strategy_mode(adaptive_policy)
  buffer_months = _cash_buffer_months_for_mode(
    industry_profile=industry_profile,
    cash_strategy_mode=cash_strategy_mode,
  )
  base_months, floor_months, interest_rate, loan_term_months = _industry_profile_or_default(
    industry_profile=industry_profile,
    adaptive_policy=adaptive_policy,
  )
  surplus_threshold = _SURPLUS_THRESHOLD_MULTIPLIER_DEFAULT

  rows_by_q = _quarter_row_lookup(finmo_json)
  if not rows_by_q:
    return CashStrategyResult(
      cash_strategy_mode=cash_strategy_mode,
      buffer_months=buffer_months,
      buffer_floor_months=floor_months,
      interest_rate=interest_rate,
      loan_term_months=loan_term_months,
      per_quarter=[],
      status="skipped",
      reason="no_finmo_quarter_rows",
    )

  debt_issuance_lever = _resolve_lever_id("debt_issuance")
  owners_capital_lever = _resolve_lever_id("owners_capital")
  other_equity_lever = _resolve_lever_id("other_equity")
  distributions_lever = _resolve_lever_id("distributions")

  # Map driver-key -> resolved lever_id so we can look up by either.
  _DRIVER_TO_LEVER: Dict[str, str] = {
    "debt_issuance": debt_issuance_lever,
    "owners_capital": owners_capital_lever,
    "other_equity": other_equity_lever,
  }
  _LEVER_TO_DRIVER: Dict[str, str] = {
    v: k for k, v in _DRIVER_TO_LEVER.items() if v
  }

  per_quarter_decisions: List[CashQuarterDecision] = []
  exact_updates: List[Dict[str, Any]] = []
  total_debt_issued = 0.0
  total_distributions = 0.0
  total_owners_capital_added = 0.0
  total_other_equity_added = 0.0

  preference_order = _MODE_FUNDING_LEVER_PREFERENCE_ORDER.get(
    cash_strategy_mode, ("debt_issuance", "owners_capital", "other_equity")
  )
  distribution_fraction = _MODE_DISTRIBUTION_FRACTION.get(cash_strategy_mode, 0.30)

  # Phase 9 corrective — inline doctrine of the smart funding source
  # policy (post_intake_cash/runner.py:1162). The function there relies
  # on runtime-bound _safe_float that's only injected via the legacy
  # convergence-runner bind path, so we re-compute the same decisions
  # here using local _safe_float. Same logic, same thresholds, same
  # output schema — death-spiral prevention via:
  #   chronic_gap (>= 5 deficit quarters) AND debt_drag_material
  #   (max_interest_rate >= 3%)  -> EXCLUDE debt_issuance
  #   NOT (chronic_gap OR leverage_material max_debt_ratio >= 55%)
  #   -> EXCLUDE other_equity (reserved for outside-investor justified)
  funding_policy: Dict[str, Any] = {}
  funding_policy_allowed_levers: List[str] = []
  funding_policy_excluded_levers: List[str] = []

  residual_gap_quarters: List[int] = []
  debt_ratios_seen: List[float] = []
  for q_pol in range(1, max(1, int(horizon)) + 1):
    row_pol = rows_by_q.get(q_pol) or {}
    cash_pol = _safe_float(row_pol.get("cash"))
    qopex_pol = _quarter_operating_expense_base(row_pol)
    monthly_pol = max(qopex_pol / 3.0, 1.0)
    buf_pol = buffer_months * monthly_pol
    if cash_pol < buf_pol:
      residual_gap_quarters.append(q_pol)
    total_debt_pol = (
      _safe_float(row_pol.get("total_debt"))
      or _safe_float(row_pol.get("long_term_debt"))
      or 0.0
    )
    total_assets_pol = (
      _safe_float(row_pol.get("total_assets"))
      or _safe_float(row_pol.get("assets"))
      or 0.0
    )
    if total_assets_pol > 0:
      debt_ratios_seen.append(float(total_debt_pol) / float(total_assets_pol))

  gap_count = len(set(residual_gap_quarters))
  chronic_gap = bool(gap_count >= 5)
  max_interest_rate = float(interest_rate or _DEFAULT_INTEREST_RATE)
  debt_drag_material = bool(max_interest_rate >= 0.03)
  max_debt_ratio = max(debt_ratios_seen) if debt_ratios_seen else 0.0
  leverage_material = bool(max_debt_ratio >= 0.55)
  external_equity_justified = bool(chronic_gap or leverage_material)

  funding_policy_allowed_levers = [
    debt_issuance_lever, owners_capital_lever, other_equity_lever
  ]
  funding_policy_allowed_levers = [x for x in funding_policy_allowed_levers if x]
  if chronic_gap and debt_drag_material and debt_issuance_lever in funding_policy_allowed_levers:
    funding_policy_allowed_levers = [
      x for x in funding_policy_allowed_levers if x != debt_issuance_lever
    ]
    funding_policy_excluded_levers.append(debt_issuance_lever)
  if not external_equity_justified and other_equity_lever in funding_policy_allowed_levers:
    funding_policy_allowed_levers = [
      x for x in funding_policy_allowed_levers if x != other_equity_lever
    ]
    funding_policy_excluded_levers.append(other_equity_lever)

  policy_reasons: List[str] = []
  if debt_issuance_lever and debt_issuance_lever in funding_policy_excluded_levers:
    policy_reasons.append(
      "Chronic liquidity gaps with material debt interest must not be solved with new debt because FINMO interest drag can reopen later cash-buffer violations."
    )
  else:
    policy_reasons.append(
      "Debt issuance remains available because the liquidity gap is not chronic or interest drag is not material."
    )
  if other_equity_lever and other_equity_lever in funding_policy_excluded_levers:
    policy_reasons.append(
      "Other Equity is reserved for outside-investor funding and is only available for chronic liquidity gaps or materially leveraged capital structures."
    )
  elif other_equity_lever and other_equity_lever in funding_policy_allowed_levers:
    policy_reasons.append(
      "Other Equity is available because the gap is chronic or leverage is material enough to justify outside-investor funding."
    )

  funding_policy = {
    "contract_version": "cash_strategy_funding_source_policy_v1",
    "allowed_funding_source_lever_ids": list(funding_policy_allowed_levers),
    "excluded_funding_source_lever_ids": list(funding_policy_excluded_levers),
    "chronic_liquidity_gap": chronic_gap,
    "residual_gap_quarter_count": gap_count,
    "max_interest_rate": round(float(max_interest_rate), 6),
    "max_debt_ratio": round(float(max_debt_ratio), 2),
    "debt_interest_drag_material": debt_drag_material,
    "external_equity_justified": external_equity_justified,
    "external_equity_semantics": (
      "Other Equity means outside investor capital such as angel, VC, silent partners, crowdfunding, "
      "or another investor ownership stake. It is not routine working-capital funding."
    ),
    "owner_capital_semantics": "Owner's Capital means owner/founder/member/insider capital contributions.",
    "policy_reason": " ".join(policy_reasons),
  }

  # Build the effective funding-source order: walk preference_order
  # (mode-driven), keep only drivers whose lever_id is in
  # funding_policy_allowed_levers (smart-policy gate). This is the
  # actual "mode chooses order within allowed sources" wiring the
  # corrective directive specified.
  effective_funding_priority: List[str] = []
  for driver_key in preference_order:
    lever_id = _DRIVER_TO_LEVER.get(driver_key, "")
    if lever_id and lever_id in funding_policy_allowed_levers:
      effective_funding_priority.append(driver_key)
  if not effective_funding_priority:
    # Smart policy excluded everything — fall back to owners_capital
    # (the safest residual lever; never excluded by the smart policy).
    if owners_capital_lever:
      effective_funding_priority = ["owners_capital"]

  # Phase 9 Gap D — Cumulative cash trough funding.
  #
  # Pre-pass: walk Q1..Q20 and identify the cumulative trough — the
  # quarter where projected ending_cash dips lowest. Compute the total
  # funding needed at the trough plus the required buffer, then
  # distribute that funding across the deficit quarters Q1..trough_q
  # as incremental per-quarter debt / owners_capital. This avoids the
  # eeea439 lump-sum dump pattern AND avoids the iter-#2 under-funding
  # caused by interest drag from issued debt.
  #
  # Universal: same algorithm regardless of business — read mode and
  # interest rate from inputs, compute trough by walking finmo rows.
  _INTEREST_DRAG_BUFFER_FACTOR = 1.15  # 15% over-fund to absorb interest drag

  trough_q: int = 1
  trough_cash: float = float("inf")
  trough_required_buffer: float = 0.0
  for q_pre in range(1, max(1, int(horizon)) + 1):
    row_pre = rows_by_q.get(q_pre) or {}
    cash_pre = _safe_float(row_pre.get("cash"))
    qopex_pre = _quarter_operating_expense_base(row_pre)
    monthly_pre = max(qopex_pre / 3.0, 1.0)
    buf_pre = buffer_months * monthly_pre
    if cash_pre < trough_cash:
      trough_cash = cash_pre
      trough_q = q_pre
      trough_required_buffer = buf_pre

  # Total deficit to fund (with interest drag buffer) — distributed
  # across Q1..trough_q. Per-quarter slice = total_deficit / num_deficit_qs.
  total_deficit_to_fund = 0.0
  per_quarter_funding_slice = 0.0
  if trough_cash < trough_required_buffer:
    total_deficit_to_fund = max(
      0.0, (trough_required_buffer - trough_cash) * _INTEREST_DRAG_BUFFER_FACTOR
    )
    deficit_quarters = max(1, int(trough_q))
    per_quarter_funding_slice = total_deficit_to_fund / float(deficit_quarters)

  cumulative_funding_applied: float = 0.0

  for q in range(1, max(1, int(horizon)) + 1):
    row = rows_by_q.get(q) or {}
    cash = _safe_float(row.get("cash"))
    revenue = _safe_float(row.get("revenue"))
    ebitda = _safe_float(row.get("ebitda"))
    quarter_opex = _quarter_operating_expense_base(row)
    monthly_opex = max(quarter_opex / 3.0, 1.0)
    required_buffer = buffer_months * monthly_opex
    surplus_threshold_value = required_buffer * surplus_threshold

    # Effective cash = observed pre-action cash + cumulative funding
    # already applied in earlier quarters (which the FINMO snapshot
    # cannot see since we rebuild only once at the end).
    effective_cash = cash + cumulative_funding_applied

    # Phase 9 Gap D: in deficit quarters (Q1..trough_q), ensure each
    # gets its cumulative-trough slice. Beyond trough_q, only fund if
    # effective_cash dips below buffer (post-trough recovery).
    if q <= trough_q and per_quarter_funding_slice > 0.0:
      funding_gap = max(per_quarter_funding_slice, required_buffer - effective_cash)
    else:
      funding_gap = max(0.0, required_buffer - effective_cash)
    surplus = max(0.0, effective_cash - surplus_threshold_value)

    decisions: Dict[str, float] = {}
    notes: List[str] = []

    # 1) Close funding gap walking effective_funding_priority (mode
    # preference filtered through smart-policy allowed sources).
    # Universal: same logic for any business; smart policy gates
    # debt_issuance when chronic + drag, gates other_equity when not
    # justified, owners_capital is always available.
    #
    # Stock vs flow semantics:
    #   - debt_issuance: FLOW (per-quarter increment); FINMO accumulates
    #     debt balance from increments + repayments.
    #   - owners_capital: STOCK (cumulative balance per quarter). Writing
    #     Q1=$X, Q2=$X gives a BALANCE of $X at both quarters (no
    #     accumulation). To inject $X/quarter we must write the running
    #     cumulative total: Q1=$X, Q2=$2X, Q3=$3X, etc.
    #   - other_equity: STOCK (same semantics as owners_capital).
    if funding_gap > 0.0 and effective_funding_priority:
      remaining = float(funding_gap)
      for driver in effective_funding_priority:
        if remaining <= 1.0:
          break
        lever_id = _DRIVER_TO_LEVER.get(driver, "")
        if not lever_id:
          continue
        amount = round(float(remaining), 2)
        decisions[driver] = amount
        cumulative_funding_applied += float(remaining)
        if driver == "debt_issuance":
          total_debt_issued += float(remaining)
          exact_updates.append({
            "lever_id": lever_id,
            "quarter_index": q,
            "exact_value": amount,
          })
        elif driver == "owners_capital":
          total_owners_capital_added += float(remaining)
          # STOCK semantics: write THIS quarter's cumulative balance only.
          # apply_exact_lever_updates_to_model_input overwrites per-quarter
          # values; later cumulative writes propagate via the existing
          # row's values, but we must explicitly set every quarter we
          # touch otherwise it's clobbered.
          exact_updates.append({
            "lever_id": lever_id,
            "quarter_index": q,
            "exact_value": round(float(total_owners_capital_added), 2),
          })
        elif driver == "other_equity":
          total_other_equity_added += float(remaining)
          exact_updates.append({
            "lever_id": lever_id,
            "quarter_index": q,
            "exact_value": round(float(total_other_equity_added), 2),
          })
        notes.append(f"funded_gap_via_{driver}:{round(remaining, 0)}")
        remaining = 0.0

    # 2) Distribute surplus per mode (NEVER raises debt to fund payouts).
    if surplus > 0.0 and ebitda > 0.0 and distribution_fraction > 0.0 and distributions_lever:
      payout = round(surplus * distribution_fraction, 2)
      if payout >= 1.0:
        decisions["distributions"] = payout
        total_distributions += payout
        exact_updates.append({
          "lever_id": distributions_lever,
          "quarter_index": q,
          "exact_value": payout,
        })
        notes.append(f"distributed_surplus:{round(payout, 0)}")

    if not decisions:
      notes.append("no_action_required")

    per_quarter_decisions.append(CashQuarterDecision(
      quarter_index=q,
      starting_cash=round(cash, 2),
      required_buffer=round(required_buffer, 2),
      funding_gap=round(funding_gap, 2),
      surplus_above_threshold=round(surplus, 2),
      ending_cash_pre_action=round(cash, 2),
      decisions=decisions,
      notes=notes,
    ))

  # Phase 9 corrective — STOCK-lever carry-forward.
  # owners_capital and other_equity are stock balances. Quarters where
  # we wrote a NEW cumulative get that value. Quarters AFTER the last
  # write must inherit the final cumulative (otherwise they retain the
  # original Q1-baseline value and the stock balance "drops" mid-horizon).
  # Build a per-lever map of quarter->cumulative. Fill any unwritten
  # quarter Q with the most recent prior write's value (carry forward).
  if total_owners_capital_added > 0 or total_other_equity_added > 0:
    by_lever_quarter: Dict[str, Dict[int, float]] = {}
    for upd in exact_updates:
      lid = str(upd.get("lever_id") or "")
      if lid not in (owners_capital_lever, other_equity_lever) or not lid:
        continue
      qi = int(upd.get("quarter_index") or 0)
      val = float(upd.get("exact_value") or 0.0)
      by_lever_quarter.setdefault(lid, {})[qi] = val
    for lid, q_map in by_lever_quarter.items():
      if not q_map:
        continue
      last_val = 0.0
      for q_idx in range(1, max(1, int(horizon)) + 1):
        if q_idx in q_map:
          last_val = q_map[q_idx]
        else:
          # Carry-forward the last cumulative balance into this quarter.
          if last_val > 0:
            exact_updates.append({
              "lever_id": lid,
              "quarter_index": q_idx,
              "exact_value": round(float(last_val), 2),
            })

  # Apply the per-quarter updates to model_input.
  if exact_updates:
    try:
      from client_intake_and_finmo.quarter_grid import (  # type: ignore
        apply_exact_lever_updates_to_model_input,
      )
      from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
        post_intake_sequence_step_scope,
      )
      with post_intake_sequence_step_scope(
        step_key="post_intake_target_seeking_post_cascade_cash",
        executor_function="phase_9_mode_based_cash_strategy",
      ):
        updated = apply_exact_lever_updates_to_model_input(
          model_input_json=model_input_json or {},
          exact_updates=exact_updates,
        )
        if isinstance(updated, dict):
          # In-place mutation: copy keys from updated into the caller's dict.
          model_input_json.clear()
          model_input_json.update(updated)
    except Exception as exc:
      return CashStrategyResult(
        cash_strategy_mode=cash_strategy_mode,
        buffer_months=buffer_months,
        buffer_floor_months=floor_months,
        interest_rate=interest_rate,
        loan_term_months=loan_term_months,
        per_quarter=per_quarter_decisions,
        total_debt_issued=total_debt_issued,
        total_distributions=total_distributions,
        total_owners_capital_added=total_owners_capital_added,
        total_other_equity_added=total_other_equity_added,
        status="failed",
        reason=f"{type(exc).__name__}: {str(exc)[:300]}",
        applied_updates_count=0,
        funding_source_policy=dict(funding_policy),
        effective_funding_priority=list(effective_funding_priority),
      )

  result = CashStrategyResult(
    cash_strategy_mode=cash_strategy_mode,
    buffer_months=buffer_months,
    buffer_floor_months=floor_months,
    interest_rate=interest_rate,
    loan_term_months=loan_term_months,
    per_quarter=per_quarter_decisions,
    total_debt_issued=round(total_debt_issued, 2),
    total_distributions=round(total_distributions, 2),
    total_owners_capital_added=round(total_owners_capital_added, 2),
    total_other_equity_added=round(total_other_equity_added, 2),
    status="completed",
    applied_updates_count=len(exact_updates),
    funding_source_policy=dict(funding_policy),
    effective_funding_priority=list(effective_funding_priority),
  )
  # Phase 9 Gap D — surface the trough diagnostic so the acceptance gate
  # and run report see how the funding was sized.
  result_dict = result.to_dict()
  result_dict["trough_diagnostic"] = {
    "trough_quarter": int(trough_q),
    "trough_cash_pre_action": round(float(trough_cash) if trough_cash != float("inf") else 0.0, 2),
    "trough_required_buffer": round(float(trough_required_buffer), 2),
    "total_deficit_to_fund_with_drag": round(float(total_deficit_to_fund), 2),
    "per_quarter_funding_slice": round(float(per_quarter_funding_slice), 2),
    "interest_drag_factor": _INTEREST_DRAG_BUFFER_FACTOR,
  }
  # Re-pack into CashStrategyResult-shaped dict by overlaying trough on the dataclass
  setattr(result, "trough_diagnostic", result_dict["trough_diagnostic"])
  return result
