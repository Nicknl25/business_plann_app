import copy
import re
from typing import Any, Dict, List, Optional


def safe_float(value: Any) -> Optional[float]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    return float(value)
  except Exception:
    return None


def canonical_cash_strategy_value(value: Any) -> str:
  text = str(value or "").strip().lower()
  if not text:
    return ""
  compact = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
  if compact in {"preserve_cash", "shareholder_return", "balanced"}:
    return compact
  if compact.startswith("balanced"):
    return "balanced"
  if compact.startswith("shareholder_return") or compact.startswith("shareholder"):
    return "shareholder_return"
  if compact.startswith("preserve_cash") or compact.startswith("preserve"):
    return "preserve_cash"
  if compact == "reinvest":
    return "balanced"
  if "balanced" in text or "mixed" in text:
    return "balanced"
  if "shareholder" in text or "distribution" in text or "payout" in text or "return capital" in text:
    return "shareholder_return"
  if "preserve" in text or "conservative" in text or "cushion" in text:
    return "preserve_cash"
  if "reinvest" in text or "growth" in text or "expansion" in text:
    return "balanced"
  return ""


def cash_strategy_policy_guidance(selected_cash_strategy: Any) -> Dict[str, Any]:
  strategy = canonical_cash_strategy_value(selected_cash_strategy) or "balanced"
  strategy_map = {
    "preserve_cash": {
      "strategy_label": "preserve_cash",
      "priority_order": [
        "satisfy_liquidity_buffer",
        "retain_extra_liquidity",
        "minimize_optional_outflows",
      ],
      "guidance": (
        "Fund only when cash would otherwise fall below the required buffer, prefer conservative non-debt "
        "support when leverage is already high, and do not create optional distributions."
      ),
    },
    "shareholder_return": {
      "strategy_label": "shareholder_return",
      "priority_order": [
        "satisfy_liquidity_buffer",
        "allow_payouts_only_from_true_excess_cash",
        "avoid_destabilizing_the_business",
      ],
      "guidance": (
        "Protect the required buffer first. Only true surplus above the buffer may be distributed, and "
        "new debt or equity must never be raised to fund shareholder payouts."
      ),
    },
    "balanced": {
      "strategy_label": "balanced",
      "priority_order": [
        "satisfy_liquidity_buffer",
        "respect_a_mixed_capital_posture",
        "avoid_extremes",
      ],
      "guidance": (
        "Fund liquidity gaps just in time, use debt and equity according to business realism and leverage, "
        "and avoid both unnecessary cash hoarding and unnecessary dilution."
      ),
    },
  }
  return copy.deepcopy(strategy_map.get(strategy) or strategy_map["balanced"])


def live_quarter_rows(finmo_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  quarter_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  return [
    row for row in quarter_rows
    if int(safe_float(row.get("quarter_index")) or 0) >= 1
  ]


def solved_lever_value_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, List[float]]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  lever_map: Dict[str, List[float]] = {}

  def _live_values(row_values: Any) -> List[float]:
    values = [float(safe_float(value) or 0.0) for value in (row_values or [])]
    if len(values) >= 21:
      return values[1:21]
    return values[:20]

  for row in [item for item in (sections.get("revenue") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = _live_values(row.get("values") or [])
  for section_name in ("expenses", "balance_sheet"):
    for row in [item for item in (sections.get(section_name) or []) if isinstance(item, dict)]:
      lever_id = str(row.get("lever_id") or "").strip()
      if lever_id:
        lever_map[lever_id] = _live_values(row.get("values") or [])
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = _live_values(row.get("values") or [])
  return lever_map


def solved_lever_stub_value_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, float]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  stub_map: Dict[str, float] = {}

  def _stub_value(row_values: Any) -> Optional[float]:
    values = [float(safe_float(value) or 0.0) for value in (row_values or [])]
    if not values:
      return None
    return float(values[0])

  for row in [item for item in (sections.get("revenue") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    stub_value = _stub_value(row.get("values") or [])
    if lever_id and stub_value is not None:
      stub_map[lever_id] = float(stub_value)
  for section_name in ("expenses", "balance_sheet"):
    for row in [item for item in (sections.get(section_name) or []) if isinstance(item, dict)]:
      lever_id = str(row.get("lever_id") or "").strip()
      stub_value = _stub_value(row.get("values") or [])
      if lever_id and stub_value is not None:
        stub_map[lever_id] = float(stub_value)
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    stub_value = _stub_value(row.get("values") or [])
    if lever_id and stub_value is not None:
      stub_map[lever_id] = float(stub_value)
  return stub_map


def operating_expense_from_row(row: Optional[Dict[str, Any]]) -> float:
  item = row if isinstance(row, dict) else {}
  return float(
    sum(
      float(safe_float(item.get(key)) or 0.0)
      for key in (
        "cost_of_goods_sold",
        "payroll",
        "marketing",
        "research_and_development",
        "lease_rent",
        "general_and_administrative",
      )
    )
  )


def capital_structure_snapshot(
  row: Optional[Dict[str, Any]],
  *,
  preferred_debt_ratio: float,
  preferred_equity_ratio: float,
) -> Dict[str, Any]:
  item = row if isinstance(row, dict) else {}
  debt_level = int(
    round(
      max(
        0.0,
        float(safe_float(item.get("short_term_debt")) or 0.0)
        + float(safe_float(item.get("long_term_debt")) or 0.0),
      )
    )
  )
  equity_level = int(round(max(0.0, float(safe_float(item.get("total_equity")) or 0.0))))
  capital_base = float(debt_level + equity_level)
  debt_ratio = round(float(debt_level / capital_base), 2) if capital_base > 1e-9 else None
  equity_ratio = round(float(equity_level / capital_base), 2) if capital_base > 1e-9 else None
  if equity_level > 0:
    debt_to_equity = round(float(debt_level / equity_level), 4)
  elif debt_level > 0:
    debt_to_equity = 999.0
  else:
    debt_to_equity = 0.0
  if debt_to_equity < 0.50:
    debt_position = "low_debt"
  elif debt_to_equity <= 1.00:
    debt_position = "healthy_debt"
  else:
    debt_position = "high_debt"
  return {
    "debt": debt_level,
    "equity": equity_level,
    "debt_level": debt_level,
    "equity_level": equity_level,
    "debt_to_equity": debt_to_equity,
    "debt_position": debt_position,
    "debt_ratio": debt_ratio,
    "equity_ratio": equity_ratio,
    "preferred_debt_ratio": round(float(preferred_debt_ratio), 2),
    "preferred_equity_ratio": round(float(preferred_equity_ratio), 2),
    "guidance_only": True,
  }


def buffer_components(
  row: Optional[Dict[str, Any]],
  *,
  cash_floor_months: Optional[float],
  cash_ceiling_months: Optional[float],
  default_buffer_months: float,
  months_per_quarter: float,
) -> Dict[str, Any]:
  """Phase 9 P3.10 iter 10 fix — units correction.

  cash_floor_months / cash_ceiling_months from the SQL cash policy
  table are MONTHS, so the base for `cash_buffer_required` and
  `cash_ceiling` must be MONTHLY operating expense, not quarterly.
  Pre-fix this function multiplied opex_quarter * floor_months,
  producing buffer thresholds 3x too large (since the FINMO
  quarter row's opex line items are quarterly amounts and
  months_per_quarter = 3). The 3x inflation cascaded into the
  validation envelope, the planning envelope, the cash strategy
  proposer's required_funding_gap, the lever_bound max sizing,
  and the finalize cash-buffer validator — manifesting as
  NexGen iter 10's `cash_buffer_invalid` despite ending_cash
  comfortably above the (correct) floor.
  """
  opex_quarter = int(round(max(0.0, operating_expense_from_row(row))))
  monthly_opex = int(round(max(0.0, float(opex_quarter) / max(float(months_per_quarter), 1.0))))
  floor_months = float(cash_floor_months if cash_floor_months is not None else default_buffer_months)
  ceiling_months = float(cash_ceiling_months if cash_ceiling_months is not None else max(floor_months, default_buffer_months))
  return {
    "operating_expense_quarter": opex_quarter,
    "buffer_months": round(float(floor_months), 2),
    "cash_floor_months": round(float(floor_months), 2),
    "cash_ceiling_months": round(float(ceiling_months), 2),
    "monthly_opex": monthly_opex,
    "cash_buffer_base_opex": monthly_opex,
    "cash_buffer_required": int(round(max(float(monthly_opex) * floor_months, 0.0))),
    "cash_ceiling": int(round(max(float(monthly_opex) * ceiling_months, 0.0))),
  }


def outstanding_gap_draw_balance_series(
  *,
  debt_issuance_series: List[int],
  debt_repayment_series: List[int],
  opening_term_debt: int,
  judged_term_quarters: Optional[int],
  horizon: int,
) -> List[int]:
  """Per-quarter CLOSING balance of outstanding gap draws (the revolver).

  RETAINED-EARNINGS-FIRST doctrine support: a business must not pay
  earnings OUT while gap-funding draws are still outstanding — earnings
  are retained until the line is repaid. This walk mirrors the debt
  schedule's term/revolver split on the lever series (stated opening
  debt amortizes on the judged term; issuance accumulates on the
  revolver; repayment above the term minimum retires the revolver
  first) so the envelopes and surplus cleanup can see how much of the
  balance is gap draws vs the structural term loan. Index 0 = Q1.
  """
  import math as _math
  term_balance = int(max(0, opening_term_debt))
  revolver_balance = 0
  series: List[int] = []
  for q in range(1, int(max(1, horizon)) + 1):
    issuance = int(debt_issuance_series[q - 1]) if q - 1 < len(debt_issuance_series) else 0
    repayment = int(debt_repayment_series[q - 1]) if q - 1 < len(debt_repayment_series) else 0
    revolver_balance = int(max(0, revolver_balance + max(0, issuance)))
    if judged_term_quarters is not None and int(judged_term_quarters) >= 1:
      remaining = max(1, int(judged_term_quarters) - q + 1)
    else:
      remaining = max(1, int(max(1, horizon)) - q + 1)
    term_min = int(min(term_balance, _math.ceil(float(term_balance) / float(remaining)))) if term_balance > 0 else 0
    repay_rev = int(min(revolver_balance, max(0, repayment - term_min)))
    repay_term = int(min(term_balance, repayment - repay_rev))
    leftover = int(max(0, repayment - repay_rev - repay_term))
    if leftover > 0:
      repay_rev += int(min(revolver_balance - repay_rev, leftover))
    revolver_balance = int(max(0, revolver_balance - repay_rev))
    term_balance = int(max(0, term_balance - repay_term))
    series.append(int(revolver_balance))
  return series


def debt_cash_support_multiplier(
  *,
  lever_map: Optional[Dict[str, List[float]]],
  quarter_index: int,
) -> float:
  if quarter_index < 1:
    return 1.0
  rate_series = (
    (lever_map or {}).get("expenses::Interest Rate")
    if isinstance(lever_map, dict)
    else []
  ) or []
  raw_rate = (
    float(safe_float(rate_series[quarter_index - 1]) or 0.0)
    if quarter_index - 1 < len(rate_series)
    else 0.0
  )
  normalized_rate = min(max(raw_rate, 0.0), 1.0)
  return round(max(0.0, 1.0 - (normalized_rate / 2.0)), 6)


def assert_cash_envelope_lifecycle(envelope: Optional[Dict[str, Any]], expected_lifecycle: str) -> None:
  payload = envelope if isinstance(envelope, dict) else {}
  actual = str(payload.get("envelope_lifecycle") or "").strip()
  if actual != expected_lifecycle:
    raise RuntimeError(
      "cash_envelope_lifecycle_mismatch: "
      f"expected={expected_lifecycle} actual={actual or 'missing'}"
    )
