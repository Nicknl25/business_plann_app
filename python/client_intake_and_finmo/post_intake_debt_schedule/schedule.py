import copy
import math
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_cash_debt_schedule_policy,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_driver_target_single_lever_id_for_target_driver,
)


DEBT_SCHEDULE_CONTRACT_VERSION = "post_intake_debt_amortization_schedule_v1"
DEBT_SCHEDULE_SOURCE_OF_TRUTH = "sql.post_intake_cash_policy_lookup"
DEBT_SCHEDULE_LOOKUP_FUNCTION = "post_intake_cash_debt_schedule_policy"

def _lookup_lever_id(target_driver: str, fallback: str) -> str:
  try:
    value = post_intake_driver_target_single_lever_id_for_target_driver(target_driver)
    return str(value or "").strip() or fallback
  except Exception:
    return fallback


DEBT_ISSUANCE_LEVER_ID = _lookup_lever_id("debt_issuance", "schedules::Debt Issuance (New Borrowing)")
DEBT_REPAYMENT_LEVER_ID = _lookup_lever_id("debt_repayment", "schedules::Debt Repayment (Scheduled)")
INTEREST_RATE_LEVER_ID = _lookup_lever_id("interest_rate", "expenses::Interest Rate")
# Phase 9 P3.10 STD canonical-source layer 3 — SHORT_TERM_DEBT_RATIO_LEVER_ID
# is removed. The lever it pointed at
# (`balance_sheet::Short Term Debt (% of LTD)`) is no longer written by
# the cash pass; FINMO computes short_term_debt directly from
# schedules::Debt Repayment for q+1..q+4. The lever may still appear as
# an inert row in model_input / Model Inputs sheet — value is always 0
# and no consumer reads it for STD computation.


def _safe_float(value: Any) -> Optional[float]:
  if value is None:
    return None
  if isinstance(value, bool):
    return 1.0 if value else 0.0
  try:
    text = str(value).strip().replace(",", "")
    if text == "":
      return None
    return float(text)
  except Exception:
    return None


def _safe_int(value: Any) -> int:
  return int(round(float(_safe_float(value) or 0.0)))


def _horizon_count(contract_name: str = "cash_strategy_review") -> int:
  count = int(post_intake_contract_forecast_horizon_quarter_count(contract_name=contract_name) or 0)
  if count <= 0:
    raise RuntimeError(
      "debt_schedule_contract_horizon_missing: "
      f"post_intake_gpt_contract_lookup must define {contract_name} forecast horizon."
    )
  return count


def _live_quarter_rows(finmo_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = finmo_payload if isinstance(finmo_payload, dict) else {}
  rows = [row for row in (payload.get("quarter_rows") or []) if isinstance(row, dict)]
  return sorted(
    [row for row in rows if int(_safe_float(row.get("quarter_index")) or 0) >= 1],
    key=lambda item: int(_safe_float(item.get("quarter_index")) or 0),
  )


def _iter_model_input_rows(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_payload in sections.values():
    if isinstance(section_payload, list):
      rows.extend([row for row in section_payload if isinstance(row, dict)])
    elif isinstance(section_payload, dict):
      rows.extend([row for row in (section_payload.get("rows") or []) if isinstance(row, dict)])
  return rows


def _row_live_values(row: Optional[Dict[str, Any]], *, horizon: int) -> List[Any]:
  values = list((row or {}).get("values") or [])
  if len(values) >= horizon + 1:
    return values[1 : horizon + 1]
  return values[:horizon]


def _lever_value_map(model_input_json: Optional[Dict[str, Any]], *, horizon: Optional[int] = None) -> Dict[str, List[float]]:
  count = int(horizon or _horizon_count())
  result: Dict[str, List[float]] = {}
  for row in _iter_model_input_rows(model_input_json):
    lever_id = str(row.get("lever_id") or "").strip()
    if not lever_id:
      section = str(row.get("section") or "").strip()
      label = str(row.get("label") or row.get("driver") or "").strip()
      if section and label:
        lever_id = f"{section}::{label}"
    if not lever_id:
      continue
    result[lever_id] = [float(_safe_float(item) or 0.0) for item in _row_live_values(row, horizon=count)]
  return result


def _capital_structure_snapshot(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  item = row if isinstance(row, dict) else {}
  debt_level = int(round(max(0.0, float(_safe_float(item.get("short_term_debt")) or 0.0) + float(_safe_float(item.get("long_term_debt")) or 0.0))))
  equity_level = int(round(max(0.0, float(_safe_float(item.get("total_equity")) or 0.0))))
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
    "debt_level": debt_level,
    "equity_level": equity_level,
    "debt_to_equity": debt_to_equity,
    "debt_position": debt_position,
  }


def cash_debt_schedule_policy_for_state(
  *,
  selected_cash_strategy: Any,
  finmo_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  rows = _live_quarter_rows(finmo_payload)
  first_row = rows[0] if rows else {}
  capital_structure = _capital_structure_snapshot(first_row)
  policy = post_intake_cash_debt_schedule_policy(
    cash_strategy=str(selected_cash_strategy or "balanced").strip().lower() or "balanced",
    debt_to_equity=capital_structure.get("debt_to_equity"),
    debt_position=capital_structure.get("debt_position"),
    required=True,
  ) or {}
  policy["capital_structure_snapshot"] = copy.deepcopy(capital_structure)
  return policy


def sba_forecast_interest_rate_policy(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  derived_policies = model_input.get("derived_driver_policies") if isinstance(model_input.get("derived_driver_policies"), dict) else {}
  debt_rate_policy = derived_policies.get("debt_interest_rate_policy") if isinstance(derived_policies.get("debt_interest_rate_policy"), dict) else {}
  debt_rate_source = debt_rate_policy.get("source_detail") if isinstance(debt_rate_policy.get("source_detail"), dict) else {}
  if not debt_rate_policy:
    raise RuntimeError(
      "debt_schedule_interest_rate_policy_missing: forecast Q1-Q20 interest rates must be backed by SBA 7(a) policy"
    )
  if str(debt_rate_source.get("source") or "").strip() != "sba_loan_7a_raw":
    raise RuntimeError(
      "debt_schedule_interest_rate_policy_not_sba_backed: forecast Q1-Q20 interest rates must use sba_loan_7a_raw"
    )
  annual_rate = _safe_float(debt_rate_policy.get("annual_rate_decimal"))
  if annual_rate is None:
    annual_rate = _safe_float(debt_rate_source.get("annual_rate_decimal"))
  if annual_rate is None or float(annual_rate) <= 0.0:
    raise RuntimeError(
      "debt_schedule_interest_rate_policy_rate_missing: SBA-backed annual_rate_decimal must be positive"
    )
  return {
    "policy": copy.deepcopy(debt_rate_policy),
    "source_detail": copy.deepcopy(debt_rate_source),
    "annual_rate_decimal": round(float(annual_rate), 6),
    # Phase 9 P3.19 — the `expenses::Interest Rate` row is consumed
    # per-quarter by FINMO / debt-schedule / workbook formulas, so
    # the per-quarter equivalent is what downstream code should
    # apply. Pre-iter, callers used annual_rate_decimal directly
    # (the per-quarter consumers then applied annual rate as if it
    # were quarterly, producing ~4x inflated interest). Callers
    # should consume quarterly_rate_decimal from here forward.
    "quarterly_rate_decimal": round(float(annual_rate) / 4.0, 6),
  }


def debt_opening_seed(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_payload: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
) -> int:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  seed = _safe_float(schedules.get("debt_opening_balance_seed"))
  if seed is not None:
    return int(round(max(0.0, float(seed))))
  rows = _live_quarter_rows(finmo_payload)
  if rows:
    opening = _safe_float(rows[0].get("debt_opening_balance"))
    if opening is not None:
      return int(round(max(0.0, float(opening))))
  financials = financials_json if isinstance(financials_json, dict) else {}
  return int(round(max(0.0, float(_safe_float(financials.get("total_debt_outstanding")) or 0.0))))


def _assert_policy_valid(policy: Dict[str, Any], *, horizon_count: int) -> None:
  if str(policy.get("debt_schedule_method") or "").strip().lower() != "amortizing_remaining_balance":
    raise RuntimeError("debt_schedule_policy_invalid: debt_schedule_method must be amortizing_remaining_balance")
  if not bool(policy.get("debt_schedule_required", True)):
    raise RuntimeError("debt_schedule_policy_invalid: debt_schedule_required must be true")
  if int(_safe_float(policy.get("debt_schedule_horizon_quarters")) or 0) != int(horizon_count):
    raise RuntimeError(
      "debt_schedule_policy_invalid: "
      f"debt_schedule_horizon_quarters must match contract horizon ({horizon_count})"
    )
  if str(policy.get("source_of_truth") or DEBT_SCHEDULE_SOURCE_OF_TRUTH).strip() != DEBT_SCHEDULE_SOURCE_OF_TRUTH:
    raise RuntimeError("debt_schedule_policy_invalid: policy must originate from sql.post_intake_cash_policy_lookup")


def build_debt_schedule_plan(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_payload: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  selected_cash_strategy: Any,
  contract_name: str = "cash_strategy_review",
) -> Dict[str, Any]:
  horizon_count = _horizon_count(contract_name)
  policy = cash_debt_schedule_policy_for_state(
    selected_cash_strategy=selected_cash_strategy,
    finmo_payload=finmo_payload,
  )
  _assert_policy_valid(policy, horizon_count=horizon_count)
  opening_debt_seed = debt_opening_seed(
    model_input_json=model_input_json,
    finmo_payload=finmo_payload,
    financials_json=financials_json,
  )
  lever_map = _lever_value_map(model_input_json, horizon=horizon_count)
  debt_issuance_series = [
    int(round(max(0.0, float(_safe_float(value) or 0.0))))
    for value in (lever_map.get(DEBT_ISSUANCE_LEVER_ID) or [])
  ]
  current_repayment_series = [
    int(round(max(0.0, float(_safe_float(value) or 0.0))))
    for value in (lever_map.get(DEBT_REPAYMENT_LEVER_ID) or [])
  ]
  interest_rate_policy = sba_forecast_interest_rate_policy(model_input_json)
  # Phase 9 P3.19 — the per-quarter rate is what we want to write
  # into the per-quarter `expenses::Interest Rate` row AND what the
  # FINMO formula `((opening + closing)/2) * rate` applies per
  # quarter. The annual rate (`annual_rate_decimal`) stays as
  # documentation of the policy basis.
  forecast_interest_rate = round(float(interest_rate_policy.get("quarterly_rate_decimal") or 0.0), 6)
  exact_updates: List[Dict[str, Any]] = []
  rows: List[Dict[str, Any]] = []
  if opening_debt_seed <= 0 and not any(debt_issuance_series):
    for quarter_index in range(1, horizon_count + 1):
      exact_updates.append(
        {
          "lever_id": INTEREST_RATE_LEVER_ID,
          "quarter_index": quarter_index,
          "exact_value": forecast_interest_rate,
          "issue_codes": ["funding_structure_mismatch"],
          "rationale": "Forecast Q1-Q20 interest-rate driver must use the SBA 7(a)-backed policy rate; stub Q0 remains intake history.",
        }
      )
    return {
      "contract_version": DEBT_SCHEDULE_CONTRACT_VERSION,
      "status": "skipped_no_debt",
      "source_of_truth": DEBT_SCHEDULE_SOURCE_OF_TRUTH,
      "lookup_function": DEBT_SCHEDULE_LOOKUP_FUNCTION,
      "policy": copy.deepcopy(policy),
      "interest_rate_policy": copy.deepcopy(interest_rate_policy),
      "schedule_method": "amortizing_remaining_balance",
      "horizon_quarters": horizon_count,
      "opening_debt_seed": 0,
      "model_input_rows_written": [INTEREST_RATE_LEVER_ID],
      "rows": rows,
      "exact_updates": exact_updates,
    }
  opening_debt = int(opening_debt_seed)
  # EXECUTIVE CASH JUDGMENT — the amortization pace follows the loan
  # TERM a real lender would extend to this business (judged, railed
  # [4, 40] quarters) instead of forcing every note to zero by the
  # horizon end. A judged 40-quarter asset-backed/project term leaves a
  # legitimate residual balance at Q20; a judged short working-capital
  # note pays down faster. No judgment -> today's pay-off-by-horizon
  # pace stands. The SBA policy rate is the rail either way.
  _judged_term_quarters: Optional[int] = None
  try:
    from client_intake_and_finmo.post_intake_cash.gpt_cash_judgment import (  # type: ignore
      cash_judgment_from_model_input as _dbt_judged_cash,
    )
    _dbt_judgment = _dbt_judged_cash(model_input_json)
    if isinstance(_dbt_judgment, dict):
      _dbt_term = _safe_float(_dbt_judgment.get("debt_term_quarters"))
      if _dbt_term and _dbt_term >= 1:
        _judged_term_quarters = int(round(_dbt_term))
  except Exception:
    _judged_term_quarters = None
  # TERM / REVOLVER SPLIT — the STATED opening debt is a TERM LOAN and
  # amortizes on the (judged) term; gap-funding draws the cash pass
  # issues are a REVOLVER: continuous draw/repay to smooth operating
  # cash carries NO forced amortization (surplus deleverage repays it).
  # Pre-split, every new draw joined the amortizing balance, so the
  # minimum-principal pace forced repayments of money the plan re-drew
  # the next quarter — revolver behavior shoved through a term-debt
  # schedule (Orion: simultaneous issue/repay every quarter). Repayment
  # applies to the revolver first (the flexible instrument), then term.
  term_balance = int(opening_debt_seed)
  revolver_balance = 0
  for quarter_index in range(1, horizon_count + 1):
    current_issuance = int(debt_issuance_series[quarter_index - 1] if quarter_index - 1 < len(debt_issuance_series) else 0)
    current_repayment = int(current_repayment_series[quarter_index - 1] if quarter_index - 1 < len(current_repayment_series) else 0)
    revolver_balance = int(max(0, revolver_balance + current_issuance))
    available_debt = int(max(0, term_balance + revolver_balance))
    if _judged_term_quarters is not None:
      remaining_quarters = max(1, _judged_term_quarters - quarter_index + 1)
    else:
      remaining_quarters = max(1, horizon_count - quarter_index + 1)
    amortizing_minimum = int(math.ceil(float(term_balance) / float(remaining_quarters))) if term_balance > 0 else 0
    minimum_principal = int(min(term_balance, amortizing_minimum))
    scheduled_principal = int(min(available_debt, max(current_repayment, minimum_principal)))
    _repay_revolver = int(min(revolver_balance, max(0, scheduled_principal - minimum_principal)))
    _repay_term = int(min(term_balance, scheduled_principal - _repay_revolver))
    _repay_leftover = int(max(0, scheduled_principal - _repay_revolver - _repay_term))
    if _repay_leftover > 0:
      _extra_rev = int(min(revolver_balance - _repay_revolver, _repay_leftover))
      _repay_revolver += _extra_rev
    revolver_balance = int(max(0, revolver_balance - _repay_revolver))
    term_balance = int(max(0, term_balance - _repay_term))
    closing_debt = int(max(0, available_debt - scheduled_principal))
    interest_rate = forecast_interest_rate
    if available_debt > 0 and interest_rate <= 0.0:
      raise RuntimeError(f"debt_schedule_interest_rate_missing: Q{quarter_index} has debt outstanding but interest rate is not positive")
    interest_expense = int(round(((opening_debt + closing_debt) / 2.0) * interest_rate))
    exact_updates.append(
      {
        "lever_id": DEBT_REPAYMENT_LEVER_ID,
        "quarter_index": quarter_index,
        "exact_value": scheduled_principal,
        "issue_codes": ["funding_structure_mismatch"],
        "rationale": "SQL cash-policy minimum debt schedule floor; cash strategy may add extra paydown but may not skip required principal.",
      }
    )
    exact_updates.append(
      {
        "lever_id": INTEREST_RATE_LEVER_ID,
        "quarter_index": quarter_index,
        "exact_value": interest_rate,
        "issue_codes": ["funding_structure_mismatch"],
        "rationale": "Forecast Q1-Q20 interest-rate driver must use the SBA 7(a)-backed policy rate; stub Q0 remains intake history.",
      }
    )
    row = {
      "quarter_index": quarter_index,
      "opening_debt": opening_debt,
      "opening_principal_balance": opening_debt,
      "new_borrowing": current_issuance,
      "actual_debt_issuance": current_issuance,
      "available_debt_before_repayment": available_debt,
      "available_principal_before_payment": available_debt,
      "minimum_principal_payment": minimum_principal,
      "scheduled_principal_payment": minimum_principal,
      "amortizing_minimum_principal": amortizing_minimum,
      "remaining_amortization_quarters": remaining_quarters,
      "extra_principal_payment": int(max(0, scheduled_principal - minimum_principal)),
      "total_principal_payment": scheduled_principal,
      "actual_debt_repayment": scheduled_principal,
      "closing_debt": closing_debt,
      "closing_principal_balance": closing_debt,
      # Instrument labeling — the schedule is a TERM LOAN (stated
      # opening debt, amortizing) plus a REVOLVER (gap-funding draws,
      # no forced amortization, repaid from surplus).
      "term_loan_closing_balance": term_balance,
      "revolver_closing_balance": revolver_balance,
      "revolver_repayment": _repay_revolver,
      "term_principal_payment": _repay_term,
      "annual_interest_rate": interest_rate,
      "interest_rate": interest_rate,
      "estimated_interest_expense": interest_expense,
      "interest_expense": interest_expense,
      "total_debt_service": int(scheduled_principal + interest_expense),
    }
    rows.append(row)
    opening_debt = closing_debt
  return {
    "contract_version": DEBT_SCHEDULE_CONTRACT_VERSION,
    "status": "ready",
    "source_of_truth": DEBT_SCHEDULE_SOURCE_OF_TRUTH,
    "lookup_function": DEBT_SCHEDULE_LOOKUP_FUNCTION,
    "policy": copy.deepcopy(policy),
    "interest_rate_policy": copy.deepcopy(interest_rate_policy),
    "schedule_method": "amortizing_remaining_balance",
    "horizon_quarters": horizon_count,
    "opening_debt_seed": int(opening_debt_seed),
    "model_input_rows_written": [DEBT_REPAYMENT_LEVER_ID, INTEREST_RATE_LEVER_ID],
    "rows": rows,
    "exact_updates": exact_updates,
  }


def build_debt_schedule_snapshot(
  *,
  finmo_payload: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  source_stage: str = "",
) -> Dict[str, Any]:
  horizon_count = _horizon_count()
  rows_by_quarter = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in _live_quarter_rows(finmo_payload)
  }
  lever_map = _lever_value_map(model_input_json, horizon=horizon_count)
  debt_issuance_series = [int(round(float(_safe_float(value) or 0.0))) for value in (lever_map.get(DEBT_ISSUANCE_LEVER_ID) or [])]
  debt_repayment_series = [int(round(float(_safe_float(value) or 0.0))) for value in (lever_map.get(DEBT_REPAYMENT_LEVER_ID) or [])]
  interest_rate_series = [round(float(_safe_float(value) or 0.0), 6) for value in (lever_map.get(INTEREST_RATE_LEVER_ID) or [])]
  # TERM/REVOLVER split — mirror the plan builder's walk on the ACTUALS
  # so the persisted snapshot rows carry the same instrument labeling
  # the declining-balance validator reads (a flat revolver balance is
  # legal; a live term balance must pay principal).
  _judged_term_q: Optional[int] = None
  try:
    from client_intake_and_finmo.post_intake_cash.gpt_cash_judgment import (  # type: ignore
      cash_judgment_from_model_input as _snap_judged_cash,
    )
    _snap_j = _snap_judged_cash(model_input_json)
    if isinstance(_snap_j, dict):
      _snap_t = _safe_float(_snap_j.get("debt_term_quarters"))
      if _snap_t and _snap_t >= 1:
        _judged_term_q = int(round(_snap_t))
  except Exception:
    _judged_term_q = None
  _first_row = rows_by_quarter.get(1) or {}
  _snap_term_balance = _safe_int(_first_row.get("debt_opening_balance"))
  _snap_revolver_balance = 0
  schedule_rows: List[Dict[str, Any]] = []
  for quarter_index in range(1, horizon_count + 1):
    row = rows_by_quarter.get(quarter_index) or {}
    opening_debt = _safe_int(row.get("debt_opening_balance"))
    requested_issuance = int(debt_issuance_series[quarter_index - 1] if quarter_index - 1 < len(debt_issuance_series) else 0)
    requested_repayment = int(debt_repayment_series[quarter_index - 1] if quarter_index - 1 < len(debt_repayment_series) else 0)
    actual_issuance = _safe_int(row.get("debt_issuance"))
    actual_repayment = _safe_int(row.get("debt_repayment"))
    _snap_revolver_balance = int(max(0, _snap_revolver_balance + actual_issuance))
    if _judged_term_q is not None:
      _snap_remaining = max(1, _judged_term_q - quarter_index + 1)
    else:
      _snap_remaining = max(1, horizon_count - quarter_index + 1)
    _snap_term_min = int(min(_snap_term_balance, math.ceil(float(_snap_term_balance) / float(_snap_remaining)))) if _snap_term_balance > 0 else 0
    _snap_repay_rev = int(min(_snap_revolver_balance, max(0, actual_repayment - _snap_term_min)))
    _snap_repay_term = int(min(_snap_term_balance, actual_repayment - _snap_repay_rev))
    _snap_leftover = int(max(0, actual_repayment - _snap_repay_rev - _snap_repay_term))
    if _snap_leftover > 0:
      _snap_repay_rev += int(min(_snap_revolver_balance - _snap_repay_rev, _snap_leftover))
    _snap_revolver_balance = int(max(0, _snap_revolver_balance - _snap_repay_rev))
    _snap_term_balance = int(max(0, _snap_term_balance - _snap_repay_term))
    closing_debt = _safe_int(row.get("debt_closing_balance") if _safe_float(row.get("debt_closing_balance")) is not None else row.get("long_term_debt"))
    interest_rate = round(
      float(_safe_float(row.get("debt_interest_rate")) if _safe_float(row.get("debt_interest_rate")) is not None else (interest_rate_series[quarter_index - 1] if quarter_index - 1 < len(interest_rate_series) else 0.0)),
      6,
    )
    interest_expense = _safe_int(row.get("debt_interest_expense") if _safe_float(row.get("debt_interest_expense")) is not None else row.get("interest"))
    schedule_rows.append(
      {
        "quarter_index": quarter_index,
        "date": row.get("date"),
        "opening_debt": opening_debt,
        "opening_principal_balance": opening_debt,
        "requested_debt_issuance": requested_issuance,
        "actual_debt_issuance": actual_issuance,
        "new_borrowing": actual_issuance,
        "requested_debt_repayment": requested_repayment,
        "actual_debt_repayment": actual_repayment,
        "total_principal_payment": actual_repayment,
        "closing_debt": closing_debt,
        "closing_principal_balance": closing_debt,
        "interest_rate": interest_rate,
        "annual_interest_rate": interest_rate,
        "interest_expense": interest_expense,
        "available_debt_before_repayment": int(max(0, opening_debt + actual_issuance)),
        "available_principal_before_payment": int(max(0, opening_debt + actual_issuance)),
        "total_debt_service": int(actual_repayment + interest_expense),
        "term_loan_closing_balance": _snap_term_balance,
        "revolver_closing_balance": _snap_revolver_balance,
        "revolver_repayment": _snap_repay_rev,
        "term_principal_payment": _snap_repay_term,
        "finmo_formula": "closing_debt = max(0, opening_debt + debt_issuance - debt_repayment); interest = average(opening_debt, closing_debt) * interest_rate",
      }
    )
  return {
    "contract_version": DEBT_SCHEDULE_CONTRACT_VERSION,
    "schedule_role": "persisted_final_debt_amortization_schedule",
    "source_of_truth": DEBT_SCHEDULE_SOURCE_OF_TRUTH,
    "lookup_function": DEBT_SCHEDULE_LOOKUP_FUNCTION,
    "source_stage": str(source_stage or "").strip(),
    "finmo_formula_unchanged": True,
    "horizon_quarters": horizon_count,
    "model_input_drivers": [INTEREST_RATE_LEVER_ID, DEBT_ISSUANCE_LEVER_ID, DEBT_REPAYMENT_LEVER_ID],
    "rows": schedule_rows,
  }


def apply_minimum_debt_schedule(
  *,
  cash_strategy_result: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  selected_cash_strategy: Any,
) -> Dict[str, Any]:
  result = copy.deepcopy(cash_strategy_result if isinstance(cash_strategy_result, dict) else {})
  model_input_json = result.get("updated_model_input_json") if isinstance(result.get("updated_model_input_json"), dict) else {}
  finmo_json = result.get("updated_finmo_json") if isinstance(result.get("updated_finmo_json"), dict) else {}
  if not model_input_json or not finmo_json:
    return result
  from client_intake_and_finmo.numeric_execution import execute_numeric_plan  # type: ignore

  schedule_plan = build_debt_schedule_plan(
    model_input_json=copy.deepcopy(model_input_json),
    finmo_payload=copy.deepcopy(finmo_json),
    financials_json=copy.deepcopy(financials_json or {}),
    selected_cash_strategy=selected_cash_strategy,
  )
  exact_updates = [copy.deepcopy(item) for item in (schedule_plan.get("exact_updates") or []) if isinstance(item, dict)]
  if not exact_updates:
    result["minimum_debt_schedule_policy"] = copy.deepcopy(schedule_plan)
    return result
  execution_result = execute_numeric_plan(
    model_input_json=copy.deepcopy(model_input_json),
    exact_updates=copy.deepcopy(exact_updates),
    numeric_solver_contract={
      "pass_name": "cash_strategy_review",
      "contract_scope": "cash_pass_minimum_debt_schedule",
      "solver_phase_status": "phase_6_cash_strategy_solver_live",
      "solver_settings": {"max_solver_attempts_per_pass": 1},
    },
    review_plan=None,
    phase_status="phase_6_cash_strategy_solver_live",
    executor_context={
      "source": "post_intake_debt_schedule.apply_minimum_debt_schedule",
      "execution_mode": "deterministic_table_backed_debt_schedule",
    },
  )
  result["updated_model_input_json"] = execution_result.get("updated_model_input_json") or model_input_json
  result["updated_finmo_json"] = execution_result.get("updated_finmo_json") or finmo_json
  result["minimum_debt_schedule_policy"] = copy.deepcopy(schedule_plan)
  applied_updates = [copy.deepcopy(item) for item in (result.get("applied_updates") or []) if isinstance(item, dict)]
  result["applied_updates"] = applied_updates + copy.deepcopy(exact_updates)
  result["applied_update_count"] = len(result["applied_updates"])
  result["applied_control_count"] = len(result["applied_updates"])
  return result


# Phase 9 P3.10 STD canonical-source layer 3 — apply_short_term_debt_current_portion
# and build_short_term_debt_current_portion_plan were deleted. Their job
# (compute STD% as ratio of next-4-quarters principal repayment over LTD,
# write the ratio into the STD% lever, downstream FINMO multiplied that
# ratio by LTD to produce short_term_debt) is now done directly in
# financial_model_engine.finmo_model.calculate_finmo_model: STD =
# sum(DEBT_REPAYMENT[q+1..q+4]) read directly from the schedule, no
# intermediate ratio, no rounding round-trip.


def validate_debt_schedule_payload(
  *,
  debt_schedule: Optional[Dict[str, Any]],
  horizon: Optional[int] = None,
) -> List[Dict[str, Any]]:
  count = int(horizon or _horizon_count())
  payload = debt_schedule if isinstance(debt_schedule, dict) else {}
  rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
  violations: List[Dict[str, Any]] = []
  if payload.get("source_of_truth") != DEBT_SCHEDULE_SOURCE_OF_TRUTH:
    violations.append({"reason": "source_of_truth_invalid", "actual": payload.get("source_of_truth")})
  if payload.get("lookup_function") != DEBT_SCHEDULE_LOOKUP_FUNCTION:
    violations.append({"reason": "lookup_function_invalid", "actual": payload.get("lookup_function")})
  quarters = sorted(int(_safe_float(row.get("quarter_index")) or 0) for row in rows)
  if quarters != list(range(1, count + 1)):
    violations.append({"reason": "horizon_invalid", "expected_quarters": list(range(1, count + 1)), "actual_quarters": quarters})
    return violations
  for row in rows:
    quarter = int(_safe_float(row.get("quarter_index")) or 0)
    opening = _safe_int(row.get("opening_debt") if row.get("opening_debt") is not None else row.get("opening_principal_balance"))
    issuance = _safe_int(row.get("actual_debt_issuance") if row.get("actual_debt_issuance") is not None else row.get("new_borrowing"))
    repayment = _safe_int(row.get("actual_debt_repayment") if row.get("actual_debt_repayment") is not None else row.get("total_principal_payment"))
    closing = _safe_int(row.get("closing_debt") if row.get("closing_debt") is not None else row.get("closing_principal_balance"))
    interest_rate = float(_safe_float(row.get("interest_rate") if row.get("interest_rate") is not None else row.get("annual_interest_rate")) or 0.0)
    interest = _safe_int(row.get("interest_expense") if row.get("interest_expense") is not None else row.get("estimated_interest_expense"))
    if int(max(0, opening + issuance - repayment)) != closing:
      violations.append({"quarter_index": quarter, "reason": "principal_rollforward_invalid", "opening": opening, "new_borrowing": issuance, "repayment": repayment, "closing": closing})
    if repayment > opening + issuance:
      violations.append({"quarter_index": quarter, "reason": "repayment_exceeds_available_principal", "available": opening + issuance, "repayment": repayment})
    if (opening > 0 or closing > 0 or issuance > 0) and interest_rate <= 0.0:
      violations.append({"quarter_index": quarter, "reason": "debt_present_but_interest_rate_missing"})
    if (opening > 0 or closing > 0 or issuance > 0) and interest < 0:
      violations.append({"quarter_index": quarter, "reason": "interest_negative", "interest": interest})
    if opening > 0 and issuance <= 0 and closing >= opening:
      # TERM/REVOLVER split — the declining-balance rule applies to the
      # TERM LOAN portion only. A revolver balance (gap-funding draws,
      # no forced amortization, repaid from surplus) legitimately sits
      # flat between draw and repayment; demanding it amortize is what
      # forced revolver draws through term-debt mechanics (the
      # simultaneous issue/repay churn). When the row carries the
      # instrument split, flag only a non-declining TERM balance.
      _term_closing = row.get("term_loan_closing_balance")
      if _term_closing is not None:
        # A live TERM balance must pay principal each quarter; a flat
        # REVOLVER balance is legal by construction.
        if _safe_int(_term_closing) > 0 and _safe_int(row.get("term_principal_payment")) <= 0:
          violations.append({
            "quarter_index": quarter,
            "reason": "term_principal_balance_not_declining_without_new_borrowing",
            "opening": opening, "closing": closing,
            "term_closing": _safe_int(_term_closing),
            "revolver_closing": _safe_int(row.get("revolver_closing_balance")),
          })
      else:
        violations.append({"quarter_index": quarter, "reason": "principal_balance_not_declining_without_new_borrowing", "opening": opening, "closing": closing})
  return violations


def validate_debt_schedule_post_cash_state(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_payload: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  selected_cash_strategy: Any,
) -> Dict[str, Any]:
  failures: List[Dict[str, Any]] = []
  try:
    schedule = build_debt_schedule_snapshot(
      finmo_payload=copy.deepcopy(finmo_payload or {}),
      model_input_json=copy.deepcopy(model_input_json or {}),
      source_stage="cash_post_validation",
    )
    failures.extend(
      {"error": "debt_schedule_payload_invalid", **violation}
      for violation in validate_debt_schedule_payload(debt_schedule=schedule)
    )
  except Exception as exc:
    schedule = {}
    failures.append({"error": "debt_schedule_snapshot_failed", "reason": str(exc)})
  try:
    minimum_plan = build_debt_schedule_plan(
      model_input_json=copy.deepcopy(model_input_json or {}),
      finmo_payload=copy.deepcopy(finmo_payload or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      selected_cash_strategy=selected_cash_strategy,
    )
  except Exception as exc:
    minimum_plan = {}
    failures.append({"error": "debt_schedule_minimum_plan_failed", "reason": str(exc)})
  lever_values = _lever_value_map(model_input_json)
  repayment_values = [max(0.0, float(_safe_float(item) or 0.0)) for item in (lever_values.get(DEBT_REPAYMENT_LEVER_ID) or [])]
  minimum_repayment_rows = {
    int(_safe_float(item.get("quarter_index")) or 0): int(round(float(_safe_float(item.get("minimum_principal_payment")) or 0.0)))
    for item in (minimum_plan.get("rows") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  under_scheduled = []
  for quarter_index, required_minimum in sorted(minimum_repayment_rows.items()):
    actual = int(round(float(repayment_values[quarter_index - 1]))) if quarter_index - 1 < len(repayment_values) else 0
    if required_minimum > 0 and actual < required_minimum:
      under_scheduled.append({"quarter_index": quarter_index, "minimum_principal_payment": required_minimum, "actual_debt_repayment": actual})
  if under_scheduled:
    failures.append({"error": "debt_schedule_minimum_principal_not_applied", "violating_quarters": under_scheduled[:20]})
  # Phase 9 P3.10 STD canonical-source layer 3 hotfix — the post-cash
  # `debt_schedule_short_term_current_portion_missing` check was removed.
  # It read the STD% lever (now an inert zero row) and would have always
  # fired as a false positive on every business with debt. STD is now
  # derived from the schedule's per-quarter principal repayment by FINMO
  # and the workbook formula (Layers 1+2).
  return {
    "status": "passed" if not failures else "failed",
    "debt_schedule_snapshot": copy.deepcopy(schedule),
    "minimum_debt_schedule_plan": copy.deepcopy(minimum_plan),
    "cash_contract_failures": failures,
  }


def assert_debt_schedule_payload_ready(
  debt_schedule: Optional[Dict[str, Any]],
  *,
  stage: str,
) -> None:
  violations = validate_debt_schedule_payload(debt_schedule=debt_schedule)
  if violations:
    raise RuntimeError(f"{stage}: debt_schedule_payload_invalid: {violations[:20]}")


def assert_finmo_matches_debt_schedule(
  *,
  debt_schedule: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  payload = debt_schedule if isinstance(debt_schedule, dict) else {}
  rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
  finmo_by_quarter = {int(_safe_float(row.get("quarter_index")) or 0): row for row in _live_quarter_rows(finmo_json)}
  violations: List[Dict[str, Any]] = []
  for row in rows:
    quarter = int(_safe_float(row.get("quarter_index")) or 0)
    finmo_row = finmo_by_quarter.get(quarter) or {}
    # Phase 9 P3.16 — `interest` in FINMO is now the COMBINED P&L
    # line (debt + lease); the debt-only portion lives in
    # `debt_interest_expense`. The schedule snapshot's
    # `interest_expense` is computed from FINMO's `debt_interest_expense`
    # (see build_debt_schedule_snapshot line ~370), so compare against
    # that same field, not the combined `interest` total.
    comparisons = [
      ("actual_debt_issuance", "debt_issuance"),
      ("actual_debt_repayment", "debt_repayment"),
      ("closing_debt", "debt_closing_balance"),
      ("interest_expense", "debt_interest_expense"),
    ]
    for schedule_field, finmo_field in comparisons:
      expected = _safe_int(row.get(schedule_field))
      actual = _safe_int(finmo_row.get(finmo_field) if finmo_field != "debt_closing_balance" else (finmo_row.get("debt_closing_balance") if _safe_float(finmo_row.get("debt_closing_balance")) is not None else finmo_row.get("long_term_debt")))
      if expected != actual:
        violations.append({"quarter_index": quarter, "schedule_field": schedule_field, "finmo_field": finmo_field, "schedule_value": expected, "finmo_value": actual})
        break
  if violations:
    raise RuntimeError(f"{stage}: debt_schedule_finmo_reconciliation_failed: {violations[:20]}")
