from __future__ import annotations

import json
import os
from itertools import combinations, product
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

try:
  from financials_year1 import apply_revenue_driver_patch  # type: ignore
except Exception:
  from client_intake_and_finmo.financials_year1 import apply_revenue_driver_patch  # type: ignore

try:
  from consistency_financials import (  # type: ignore
    build_consistency_financial_summary,
    build_consistency_financial_table,
  )
except Exception:
  from client_intake_and_finmo.consistency_financials import (  # type: ignore
    build_consistency_financial_summary,
    build_consistency_financial_table,
  )


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _float_env(name: str, default: float) -> float:
  _load_root_env()
  raw = str(os.getenv(name) or "").strip()
  if not raw:
    return default
  try:
    return float(raw)
  except Exception:
    return default


def _bool_env(name: str, default: bool) -> bool:
  _load_root_env()
  raw = str(os.getenv(name) or "").strip().lower()
  if not raw:
    return default
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  return default


LOSS_THRESHOLD_RATIO = _float_env("CONSISTENCY_NET_LOSS_THRESHOLD_RATIO", 0.15)
PRICE_STEP_PCTS: Tuple[float, ...] = (0.05, 0.10)
UTILIZATION_STEP_PTS: Tuple[float, ...] = (0.05, 0.10)
MARKETING_REDUCTION_PCTS: Tuple[float, ...] = (0.10, 0.20)
OTHER_OPEX_REDUCTION_PCTS: Tuple[float, ...] = (0.10, 0.20)
HIRE_DELAY_STEPS_MONTHS: Tuple[int, ...] = (3, 6, 9, 12, 15)
MAX_SCENARIOS = 3
ROLE_WAGE_MIN_FACTOR = _float_env("CONSISTENCY_ROLE_WAGE_MIN_FACTOR", 0.85)
ROLE_WAGE_MAX_FACTOR = _float_env("CONSISTENCY_ROLE_WAGE_MAX_FACTOR", 1.00)
ENABLE_PRICE_LEVER = _bool_env("CONSISTENCY_SOLVER_ENABLE_PRICE", False)
PRICE_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_PRICE_WEIGHT", 12.0)
UTILIZATION_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_UTILIZATION_WEIGHT", 4.0)
MARKETING_UP_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_MARKETING_UP_WEIGHT", 4.0)
MARKETING_DOWN_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_MARKETING_DOWN_WEIGHT", 5.0)
OTHER_OPEX_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_OTHER_OPEX_WEIGHT", 2.0)
HIRE_DELAY_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_HIRE_DELAY_WEIGHT", 6.0)
PAYROLL_DOWN_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_PAYROLL_WEIGHT", 8.0)
FAMILY_CONCENTRATION_WEIGHT = _float_env("CONSISTENCY_SOLVER_FAMILY_CONCENTRATION_WEIGHT", 6.0)
HEALTHY_EBITDA_MARGIN_RATIO = _float_env("CONSISTENCY_SOLVER_HEALTHY_EBITDA_MARGIN_RATIO", 0.05)
EBITDA_CUSHION_PREFERENCE_WEIGHT = _float_env("CONSISTENCY_SOLVER_EBITDA_CUSHION_WEIGHT", 1.5)
OPTION_OBJECTIVE_TOLERANCE_RATIO = _float_env("CONSISTENCY_SOLVER_OPTION_TOLERANCE_RATIO", 0.03)
OPTION_OBJECTIVE_TOLERANCE_ABS = _float_env("CONSISTENCY_SOLVER_OPTION_TOLERANCE_ABS", 0.05)


def _require_pulp():
  try:
    import pulp  # type: ignore
  except Exception as exc:
    raise RuntimeError("PuLP is required for the consistency solver.") from exc
  return pulp


def _clone(value: Any) -> Any:
  return json.loads(json.dumps(value, ensure_ascii=False))


def _safe_float(value: Any) -> float:
  if value is None or value == "" or isinstance(value, bool):
    return 0.0
  try:
    num = float(value)
  except Exception:
    return 0.0
  if num != num:
    return 0.0
  return num


def _safe_int(value: Any) -> Optional[int]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    return int(round(float(value)))
  except Exception:
    return None


def _normalize_ratio(value: Any) -> Optional[float]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    ratio = float(value)
  except Exception:
    return None
  if ratio > 1.0:
    ratio = ratio / 100.0
  ratio = max(0.0, min(1.0, ratio))
  return ratio


def _format_currency(value: Any) -> str:
  amount = _safe_float(value)
  return f"${amount:,.0f}" if abs(amount - round(amount)) < 1e-9 else f"${amount:,.2f}"


def _format_percent(value: Any) -> str:
  ratio = _normalize_ratio(value)
  if ratio is None:
    return "0%"
  return f"{ratio * 100:.0f}%"


def _loss_pct(summary: Dict[str, Any]) -> float:
  revenue = _safe_float((summary or {}).get("revenue"))
  net_income = _safe_float((summary or {}).get("net_income"))
  if revenue <= 0:
    return 0.0 if net_income >= 0 else 1.0
  return max(0.0, -net_income / revenue)


def _solver_required(summary: Dict[str, Any]) -> bool:
  revenue = _safe_float((summary or {}).get("revenue"))
  net_income = _safe_float((summary or {}).get("net_income"))
  ebitda = _safe_float((summary or {}).get("ebitda"))
  if revenue <= 0:
    return net_income < 0
  healthy_target = max(0.0, revenue * HEALTHY_EBITDA_MARGIN_RATIO)
  return ebitda < healthy_target or (_loss_pct(summary) > LOSS_THRESHOLD_RATIO)


def _ebitda_gap(summary: Dict[str, Any]) -> float:
  return max(0.0, -_safe_float((summary or {}).get("ebitda")))


def _is_break_even_ebitda(summary: Dict[str, Any]) -> bool:
  return _safe_float((summary or {}).get("ebitda")) >= 0.0


def _top_level_driver_value(payload: Dict[str, Any], key: str) -> Optional[float]:
  value = payload.get(key)
  if value is not None and value != "":
    try:
      return float(value)
    except Exception:
      pass
  lobs = payload.get("lobs")
  if not isinstance(lobs, list):
    return None
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      if product.get(key) is None or product.get(key) == "":
        continue
      try:
        return float(product.get(key))
      except Exception:
        continue
  return None


def _required_units_year1(financials_year1_json: Dict[str, Any]) -> float:
  total = 0.0
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  lobs = year1.get("lobs")
  if isinstance(lobs, list):
    for lob in lobs:
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product in products:
        if not isinstance(product, dict):
          continue
        avg_units = _safe_float(product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1"))
        periods = _safe_float(product.get("operating_periods_per_year") or product.get("operating_weeks_per_year"))
        total += avg_units * periods
  if total > 0:
    return total
  avg_units = _safe_float(year1.get("avg_units_per_period_year1") or year1.get("avg_units_per_week_year1"))
  periods = _safe_float(year1.get("operating_periods_per_year") or year1.get("operating_weeks_per_year"))
  return avg_units * periods


def _recompute_payroll_fields(
  *,
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  roles_basis: List[Dict[str, Any]] = []
  total = 0.0

  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    annual_wage = max(0.0, _safe_float(person.get("annual_wage")))
    total += annual_wage
    roles_basis.append(
      {
        "source": "person",
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_counted_year1": 12,
        "year1_payroll_amount": annual_wage,
      }
    )

  for role in (people_json or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    annual_wage = max(0.0, _safe_float(role.get("annual_wage")))
    raw_months = _safe_int(role.get("months_until_hire"))
    months_until_hire = max(0, raw_months if raw_months is not None else 0)
    months_counted = max(0, 12 - min(12, months_until_hire))
    year1_amount = annual_wage * (months_counted / 12.0)
    total += year1_amount
    roles_basis.append(
      {
        "source": "inferred_role",
        "role_title": str(role.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_until_hire": months_until_hire,
        "months_counted_year1": months_counted,
        "year1_payroll_amount": year1_amount,
      }
    )

  next_financials["baseline_payroll_year1"] = float(total)
  next_financials["payroll_adjustment"] = 0.0
  next_financials["payroll_total_year1"] = float(total)
  next_financials["payroll_basis_people_roles"] = roles_basis
  next_financials["current_payroll"] = float(total)
  return next_financials


def _apply_marketing_total(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  total: float,
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  revenue = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
  baseline_amount = _safe_float(next_financials.get("baseline_marketing"))
  baseline_percent = _safe_float(next_financials.get("baseline_marketing_percent"))
  if baseline_amount <= 0 and baseline_percent > 0 and revenue > 0:
    baseline_amount = revenue * baseline_percent

  total = max(0.0, float(total))
  next_financials["marketing_total_year1"] = total
  next_financials["marketing_percent_of_revenue"] = float(total / revenue) if revenue > 0 else 0.0
  if baseline_amount > 0:
    next_financials["baseline_marketing"] = baseline_amount
    next_financials["marketing_adjustment"] = total - baseline_amount
  if baseline_percent > 0:
    next_financials["baseline_marketing_percent"] = baseline_percent
  return next_financials


def _apply_marketing_model_patch(
  *,
  marketing_model_json: Dict[str, Any],
  patch: Dict[str, Any],
) -> Dict[str, Any]:
  next_model = dict(marketing_model_json or {})
  for key, value in (patch or {}).items():
    next_model[str(key)] = value
  return next_model


def _marketing_units_per_dollar(marketing_model_json: Optional[Dict[str, Any]]) -> float:
  model = marketing_model_json if isinstance(marketing_model_json, dict) else {}
  baseline_marketing = max(
    0.0,
    _safe_float(model.get("marketing_total_year1"))
    or _safe_float(model.get("baseline_marketing")),
  )
  expected_units = max(0.0, _safe_float(model.get("expected_units_year1")))
  if baseline_marketing <= 0 or expected_units <= 0:
    return 0.0
  return expected_units / max(baseline_marketing, 1e-9)


def _sync_marketing_derived_fields(
  *,
  marketing_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  units_per_dollar: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_model = dict(marketing_model_json or {})
  next_financials = dict(financials_json or {})
  units_per_dollar = max(0.0, _safe_float(units_per_dollar))
  if units_per_dollar <= 0:
    units_per_dollar = _marketing_units_per_dollar(next_model)
  expected_units = max(0.0, _safe_float(next_model.get("expected_units_year1")))
  if units_per_dollar > 0 and expected_units >= 0:
    marketing_total = round(expected_units / units_per_dollar, 2)
    next_model["marketing_total_year1"] = marketing_total
    next_financials = _apply_marketing_total(
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      total=marketing_total,
    )
  reachable_market = max(0.0, _safe_float(next_model.get("reachable_market")))
  if reachable_market > 0 and expected_units >= 0:
    next_model["capture_rate_year1"] = round(expected_units / max(reachable_market, 1e-9), 6)
  baseline_expected_units = max(0.0, _safe_float(next_model.get("required_units_year1")))
  baseline_expected_customers = max(0.0, _safe_float(next_model.get("expected_customers_or_clients_year1")))
  if baseline_expected_units > 0 and baseline_expected_customers > 0 and expected_units >= 0:
    scaled_customers = baseline_expected_customers * (expected_units / max(baseline_expected_units, 1e-9))
    if reachable_market > 0:
      scaled_customers = min(reachable_market, scaled_customers)
    next_model["expected_customers_or_clients_year1"] = round(scaled_customers, 2)
  return next_model, next_financials


def _apply_other_opex_total(
  *,
  financials_json: Dict[str, Any],
  total: float,
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  next_financials["other_operating_expense"] = max(0.0, float(total))
  return next_financials


def _render_timing_text(months: int) -> str:
  months = max(1, int(months))
  if months == 1:
    return "within 1 month"
  return f"within {months} months"


def _attach_milestone_updates_for_delay(
  *,
  ops_json: Dict[str, Any],
  minimum_months: int,
) -> List[Dict[str, Any]]:
  updates: List[Dict[str, Any]] = []
  milestones = (ops_json or {}).get("milestones") or []
  if not isinstance(milestones, list):
    return updates
  for index, milestone in enumerate(milestones):
    if not isinstance(milestone, dict):
      continue
    timing_months = _safe_int(milestone.get("timing_months_max"))
    if timing_months is None or timing_months >= minimum_months:
      continue
    updates.append(
      {
        "index": index,
        "timing_months_max": int(minimum_months),
        "timing": _render_timing_text(int(minimum_months)),
      }
    )
  return updates


def _candidate_disruption_score(exact_patches: Dict[str, Any]) -> float:
  score = 0.0
  lever_count = 0

  year1_patch = exact_patches.get("financials_year1_patch")
  if isinstance(year1_patch, dict):
    if year1_patch.get("utilization_rate") is not None:
      lever_count += 1
      score += abs(_safe_float(year1_patch.get("utilization_rate")))
    if year1_patch.get("unit_price") is not None:
      lever_count += 1
      score += 1.0

  financials_patch = exact_patches.get("financials_patch")
  if isinstance(financials_patch, dict):
    if financials_patch.get("marketing_total_year1") is not None:
      lever_count += 1
      score += 0.75
    if financials_patch.get("other_operating_expense") is not None:
      lever_count += 1
      score += 0.5
  marketing_model_patch = exact_patches.get("marketing_model_patch")
  if isinstance(marketing_model_patch, dict) and marketing_model_patch.get("expected_units_year1") is not None:
    lever_count += 1
    score += 0.75

  role_updates = exact_patches.get("people_role_updates")
  if isinstance(role_updates, list) and role_updates:
    lever_count += len(role_updates)
    for item in role_updates:
      if not isinstance(item, dict):
        continue
      score += max(0.0, (_safe_int(item.get("months_until_hire")) or 0) / 12.0)
      if item.get("annual_wage") is not None:
        score += 1.5

  milestone_updates = exact_patches.get("milestone_updates")
  if isinstance(milestone_updates, list) and milestone_updates:
    lever_count += 1
    score += 0.25

  return score + (0.35 * lever_count)


def _apply_exact_patches(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  exact_patches: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  next_ops = _clone(ops_json or {})
  next_people = _clone(people_json or {})
  next_financials = _clone(financials_json or {})
  next_year1 = _clone(financials_year1_json or {})
  next_marketing_model = _clone(marketing_model_json or {})

  year1_patch = exact_patches.get("financials_year1_patch")
  if isinstance(year1_patch, dict) and year1_patch:
    next_year1 = apply_revenue_driver_patch(next_year1, year1_patch)

  role_updates = exact_patches.get("people_role_updates")
  if isinstance(role_updates, list) and isinstance(next_people.get("inferred_roles"), list):
    roles = next_people.get("inferred_roles") or []
    for update in role_updates:
      if not isinstance(update, dict):
        continue
      role_title = str(update.get("role_title") or "").strip().lower()
      months = _safe_int(update.get("months_until_hire"))
      annual_wage = _safe_float(update.get("annual_wage")) if update.get("annual_wage") is not None else None
      if not role_title or months is None:
        continue
      for role in roles:
        if not isinstance(role, dict):
          continue
        if str(role.get("role_title") or "").strip().lower() != role_title:
          continue
        role["months_until_hire"] = int(max(0, months))
        if annual_wage is not None and annual_wage > 0:
          role["annual_wage"] = float(annual_wage)
        break

  financials_patch = exact_patches.get("financials_patch")
  if isinstance(financials_patch, dict):
    for key, value in financials_patch.items():
      next_financials[str(key)] = value

  milestone_updates = exact_patches.get("milestone_updates")
  milestones = next_ops.get("milestones")
  if isinstance(milestone_updates, list) and isinstance(milestones, list):
    for update in milestone_updates:
      if not isinstance(update, dict):
        continue
      index = _safe_int(update.get("index"))
      if index is None or index < 0 or index >= len(milestones):
        continue
      milestone = milestones[index]
      if not isinstance(milestone, dict):
        continue
      if update.get("timing_months_max") is not None:
        milestone["timing_months_max"] = int(max(1, _safe_int(update.get("timing_months_max")) or 1))
      if str(update.get("timing") or "").strip():
        milestone["timing"] = str(update.get("timing") or "").strip()

  next_financials = _recompute_payroll_fields(
    people_json=next_people,
    financials_json=next_financials,
  )

  if isinstance(financials_patch, dict) and "marketing_total_year1" in financials_patch:
    next_financials = _apply_marketing_total(
      financials_json=next_financials,
      financials_year1_json=next_year1,
      total=_safe_float(financials_patch.get("marketing_total_year1")),
    )
  elif next_financials.get("marketing_total_year1") is not None:
    next_financials = _apply_marketing_total(
      financials_json=next_financials,
      financials_year1_json=next_year1,
      total=_safe_float(next_financials.get("marketing_total_year1")),
    )

  if isinstance(financials_patch, dict) and "other_operating_expense" in financials_patch:
    next_financials = _apply_other_opex_total(
      financials_json=next_financials,
      total=_safe_float(financials_patch.get("other_operating_expense")),
    )

  marketing_model_patch = exact_patches.get("marketing_model_patch")
  if isinstance(marketing_model_patch, dict) and marketing_model_patch:
    baseline_units_per_dollar = _marketing_units_per_dollar(next_marketing_model)
    next_marketing_model = _apply_marketing_model_patch(
      marketing_model_json=next_marketing_model,
      patch=marketing_model_patch,
    )
    next_marketing_model, next_financials = _sync_marketing_derived_fields(
      marketing_model_json=next_marketing_model,
      financials_json=next_financials,
      financials_year1_json=next_year1,
      units_per_dollar=baseline_units_per_dollar,
    )

  return next_ops, next_people, next_financials, next_year1, next_marketing_model


def _scenario_violations(
  *,
  baseline_state: Dict[str, Any],
  next_ops: Dict[str, Any],
  next_financials: Dict[str, Any],
  next_year1: Dict[str, Any],
  exact_patches: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
) -> List[str]:
  del baseline_state, next_ops, next_financials, exact_patches, marketing_model_json
  next_required_units = _required_units_year1(next_year1 or {})
  if next_required_units < 0:
    return ["required units must be non-negative"]
  return []


def _scenario_signature(exact_patches: Dict[str, Any]) -> str:
  return json.dumps(exact_patches or {}, sort_keys=True, ensure_ascii=False)


def _build_candidate(
  *,
  scenario_id: str,
  baseline_summary: Dict[str, Any],
  baseline_state: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  label: str,
  rationale: str,
  lever_families: Sequence[str],
  exact_patches: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  next_ops, next_people, next_financials, next_year1, next_marketing_model = _apply_exact_patches(
    ops_json=baseline_state.get("ops_json") or {},
    people_json=baseline_state.get("people_json") or {},
    financials_json=baseline_state.get("financials_json") or {},
    financials_year1_json=baseline_state.get("financials_year1_json") or {},
    marketing_model_json=baseline_state.get("marketing_model_json") or marketing_model_json or {},
    exact_patches=exact_patches,
  )
  summary = build_consistency_financial_summary(
    financials_json=next_financials,
    financials_year1_json=next_year1,
  )
  violations = _scenario_violations(
    baseline_state=baseline_state,
    next_ops=next_ops,
    next_financials=next_financials,
    next_year1=next_year1,
    exact_patches=exact_patches,
    marketing_model_json=next_marketing_model,
  )
  if violations:
    return None
  baseline_net_income = _safe_float(baseline_summary.get("net_income"))
  next_net_income = _safe_float(summary.get("net_income"))
  improvement = next_net_income - baseline_net_income
  if improvement <= 0:
    return None

  disruption_score = _candidate_disruption_score(exact_patches)
  is_break_even = _is_break_even_ebitda(summary)
  ebitda_gap = _ebitda_gap(summary)

  return {
    "scenario_id": scenario_id,
    "label": label,
    "rationale": rationale,
    "lever_families": list(lever_families),
    "exact_patches": exact_patches,
    "summary": summary,
    "ebitda": _safe_float(summary.get("ebitda")),
    "net_income": next_net_income,
    "loss_pct": _loss_pct(summary),
    "ebitda_gap": ebitda_gap,
    "break_even_ebitda": is_break_even,
    "disruption_score": disruption_score,
    "improvement_amount": improvement,
    "signature": _scenario_signature(exact_patches),
    "editable_role_titles": [
      str(update.get("role_title") or "").strip()
      for update in (exact_patches.get("people_role_updates") or [])
      if isinstance(update, dict) and str(update.get("role_title") or "").strip()
    ],
    "editable_milestone_indexes": [
      int(_safe_int(update.get("index")) or 0)
      for update in (exact_patches.get("milestone_updates") or [])
      if isinstance(update, dict) and _safe_int(update.get("index")) is not None
    ],
  }


def _merge_exact_patches(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
  merged: Dict[str, Any] = {}
  for key in ("financials_year1_patch", "financials_patch"):
    base = first.get(key) if isinstance(first, dict) else None
    extra = second.get(key) if isinstance(second, dict) else None
    combined: Dict[str, Any] = {}
    if isinstance(base, dict):
      combined.update(base)
    if isinstance(extra, dict):
      combined.update(extra)
    if combined:
      merged[key] = combined

  role_updates: Dict[str, Dict[str, Any]] = {}
  for source in (first.get("people_role_updates"), second.get("people_role_updates")):
    if not isinstance(source, list):
      continue
    for item in source:
      if not isinstance(item, dict):
        continue
      role_title = str(item.get("role_title") or "").strip().lower()
      if not role_title:
        continue
      role_updates[role_title] = dict(item)
  if role_updates:
    merged["people_role_updates"] = list(role_updates.values())

  milestone_updates: Dict[int, Dict[str, Any]] = {}
  for source in (first.get("milestone_updates"), second.get("milestone_updates")):
    if not isinstance(source, list):
      continue
    for item in source:
      if not isinstance(item, dict):
        continue
      index = _safe_int(item.get("index"))
      if index is None:
        continue
      current = milestone_updates.get(index, {})
      current.update(item)
      milestone_updates[index] = current
  if milestone_updates:
    merged["milestone_updates"] = [milestone_updates[idx] for idx in sorted(milestone_updates)]

  return merged


def _select_top_candidates(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  all_candidates = _dedupe_by_economic_outcome(
    [candidate for candidate in candidates if isinstance(candidate, dict)]
  )
  if not all_candidates:
    return []

  pulp = _require_pulp()
  break_even_target_exists = any(bool(candidate.get("break_even_ebitda")) for candidate in all_candidates)
  selected: List[Dict[str, Any]] = []
  excluded_signatures = set()

  while len(selected) < MAX_SCENARIOS:
    pool = [
      candidate
      for candidate in all_candidates
      if _economic_signature(candidate) not in excluded_signatures
    ]
    if not pool:
      break

    problem = pulp.LpProblem("consistency_solver_select", pulp.LpMaximize)
    vars_by_idx = {
      idx: pulp.LpVariable(f"pick_{idx}", lowBound=0, upBound=1, cat="Binary")
      for idx in range(len(pool))
    }
    problem += pulp.lpSum(vars_by_idx.values()) == 1
    problem += pulp.lpSum(
      _candidate_objective(candidate, break_even_target_exists=break_even_target_exists) * vars_by_idx[idx]
      for idx, candidate in enumerate(pool)
    )
    problem.solve(pulp.PULP_CBC_CMD(msg=False))
    chosen_idx = None
    for idx, variable in vars_by_idx.items():
      try:
        value = float(variable.value())
      except Exception:
        value = 0.0
      if value >= 0.5:
        chosen_idx = idx
        break
    if chosen_idx is None:
      break
    chosen = pool[chosen_idx]
    selected.append(chosen)
    excluded_signatures.add(_economic_signature(chosen))

  return selected


def _primary_family(candidate: Dict[str, Any]) -> str:
  families = candidate.get("lever_families") if isinstance(candidate, dict) else None
  if not isinstance(families, list) or not families:
    return ""
  return str(families[0] or "").strip()


def _economic_signature(candidate: Dict[str, Any]) -> str:
  return json.dumps(
    {
      "ebitda": round(_safe_float(candidate.get("ebitda")), 2),
      "net_income": round(_safe_float(candidate.get("net_income")), 2),
      "loss_pct": round(_safe_float(candidate.get("loss_pct")), 6),
      "break_even_ebitda": bool(candidate.get("break_even_ebitda")),
    },
    sort_keys=True,
    ensure_ascii=False,
  )


def _dedupe_by_economic_outcome(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  deduped: List[Dict[str, Any]] = []
  seen = set()
  for candidate in candidates:
    if not isinstance(candidate, dict):
      continue
    signature = _economic_signature(candidate)
    if not signature or signature in seen:
      continue
    seen.add(signature)
    deduped.append(candidate)
  return deduped


def _role_update_map(candidate: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  updates = (candidate.get("exact_patches") or {}).get("people_role_updates") if isinstance(candidate, dict) else None
  updates = updates if isinstance(updates, list) else []
  mapped: Dict[str, Dict[str, Any]] = {}
  for item in updates:
    if not isinstance(item, dict):
      continue
    role_title = str(item.get("role_title") or "").strip().lower()
    if role_title:
      mapped[role_title] = item
  return mapped


def _materially_distinct_candidate(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
  left_patch = left.get("exact_patches") if isinstance(left, dict) else {}
  right_patch = right.get("exact_patches") if isinstance(right, dict) else {}
  left_year1 = left_patch.get("financials_year1_patch") if isinstance(left_patch, dict) else {}
  right_year1 = right_patch.get("financials_year1_patch") if isinstance(right_patch, dict) else {}
  left_marketing = left_patch.get("marketing_model_patch") if isinstance(left_patch, dict) else {}
  right_marketing = right_patch.get("marketing_model_patch") if isinstance(right_patch, dict) else {}

  left_util = _normalize_ratio((left_year1 or {}).get("utilization_rate"))
  right_util = _normalize_ratio((right_year1 or {}).get("utilization_rate"))
  if left_util is not None and right_util is not None and abs(left_util - right_util) >= 0.01:
    return True

  left_units = _safe_float((left_marketing or {}).get("expected_units_year1"))
  right_units = _safe_float((right_marketing or {}).get("expected_units_year1"))
  if max(left_units, right_units) > 0 and abs(left_units - right_units) >= max(1.0, 0.02 * max(left_units, right_units)):
    return True

  left_roles = _role_update_map(left)
  right_roles = _role_update_map(right)
  if set(left_roles.keys()) != set(right_roles.keys()):
    return True
  for role_title in left_roles.keys():
    left_item = left_roles.get(role_title) or {}
    right_item = right_roles.get(role_title) or {}
    if abs((_safe_int(left_item.get("months_until_hire")) or 0) - (_safe_int(right_item.get("months_until_hire")) or 0)) >= 1:
      return True
    left_wage = _safe_float(left_item.get("annual_wage"))
    right_wage = _safe_float(right_item.get("annual_wage"))
    if max(left_wage, right_wage) > 0 and abs(left_wage - right_wage) >= max(250.0, 0.01 * max(left_wage, right_wage)):
      return True
  return False


def _candidate_objective(candidate: Dict[str, Any], *, break_even_target_exists: bool) -> float:
  break_even = 1.0 if bool(candidate.get("break_even_ebitda")) else 0.0
  ebitda_gap = _safe_float(candidate.get("ebitda_gap"))
  ebitda = _safe_float(candidate.get("ebitda"))
  net_income = _safe_float(candidate.get("net_income"))
  disruption = _safe_float(candidate.get("disruption_score"))
  improvement = _safe_float(candidate.get("improvement_amount"))
  if break_even_target_exists:
    return (
      1_000_000.0 * break_even
      - 1_000.0 * disruption
      + ebitda
      + 0.01 * net_income
      + 0.001 * improvement
    )
  return (
    -10_000.0 * ebitda_gap
    + ebitda
    + 0.01 * net_income
    - 10.0 * disruption
    + 0.001 * improvement
  )


def _collect_solver_roles(people_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  all_role_wages: List[float] = []
  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    annual_wage = _safe_float(person.get("annual_wage"))
    if annual_wage > 0:
      all_role_wages.append(annual_wage)
  for role in (people_json or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    annual_wage = _safe_float(role.get("annual_wage"))
    if annual_wage > 0:
      all_role_wages.append(annual_wage)
  all_role_wages = sorted({round(wage, 2) for wage in all_role_wages if wage > 0})

  roles_out: List[Dict[str, Any]] = []
  roles = (people_json or {}).get("inferred_roles") or []
  if not isinstance(roles, list):
    return roles_out
  for role in roles:
    if not isinstance(role, dict):
      continue
    annual_wage = _safe_float(role.get("annual_wage"))
    if annual_wage <= 0:
      continue
    role_title = str(role.get("role_title") or "").strip()
    if not role_title:
      continue
    base_months = max(0, min(12, _safe_int(role.get("months_until_hire")) or 0))
    baseline_year1_amount = annual_wage * ((12.0 - float(base_months)) / 12.0)
    if baseline_year1_amount <= 0:
      continue
    lower_neighbors = [wage for wage in all_role_wages if wage < annual_wage - 0.01]
    upper_neighbors = [wage for wage in all_role_wages if wage > annual_wage + 0.01]
    nearest_lower = max(lower_neighbors) if lower_neighbors else annual_wage * ROLE_WAGE_MIN_FACTOR
    nearest_upper = min(upper_neighbors) if upper_neighbors else annual_wage
    wage_floor = max(0.0, min(annual_wage, (annual_wage + nearest_lower) / 2.0))
    wage_ceiling = max(wage_floor, min(annual_wage, nearest_upper))
    roles_out.append(
      {
        "role_title": role_title,
        "annual_wage": annual_wage,
        "base_months": base_months,
        "baseline_year1_amount": baseline_year1_amount,
        "wage_floor": wage_floor,
        "wage_ceiling": wage_ceiling,
      }
    )
  roles_out.sort(key=lambda item: item.get("baseline_year1_amount") or 0.0, reverse=True)
  return roles_out


def _semantic_value(
  *,
  value: Any,
  metric_type: str,
  unit_basis: str,
  time_basis: str,
  hard_constraint_eligible: bool,
  transform_required: Optional[str] = None,
) -> Dict[str, Any]:
  return {
    "value": value,
    "metric_type": str(metric_type or "").strip(),
    "unit_basis": str(unit_basis or "").strip(),
    "time_basis": str(time_basis or "").strip(),
    "hard_constraint_eligible": bool(hard_constraint_eligible),
    "transform_required": str(transform_required or "").strip() or None,
  }


def _semantic_value_number(payload: Any) -> float:
  if isinstance(payload, dict):
    return _safe_float(payload.get("value"))
  return _safe_float(payload)


def _semantic_values_compatible(left: Any, right: Any) -> bool:
  if not isinstance(left, dict) or not isinstance(right, dict):
    return False
  if not bool(left.get("hard_constraint_eligible")):
    return False
  if not bool(right.get("hard_constraint_eligible")):
    return False
  if str(left.get("transform_required") or "").strip():
    return False
  if str(right.get("transform_required") or "").strip():
    return False
  return (
    str(left.get("metric_type") or "").strip() == str(right.get("metric_type") or "").strip()
    and str(left.get("unit_basis") or "").strip() == str(right.get("unit_basis") or "").strip()
    and str(left.get("time_basis") or "").strip() == str(right.get("time_basis") or "").strip()
  )


def _constraint_source_value(
  constraint_basis: Dict[str, Any],
  key: str,
) -> Optional[Dict[str, Any]]:
  payload = constraint_basis.get(key) if isinstance(constraint_basis, dict) else None
  return payload if isinstance(payload, dict) else None


def _build_constraint_audit(constraint_basis: Dict[str, Any]) -> List[Dict[str, Any]]:
  audit: List[Dict[str, Any]] = []
  for key, payload in (constraint_basis or {}).items():
    if not isinstance(payload, dict):
      continue
    audit.append(
      {
        "field": str(key),
        "metric_type": str(payload.get("metric_type") or "").strip(),
        "unit_basis": str(payload.get("unit_basis") or "").strip(),
        "time_basis": str(payload.get("time_basis") or "").strip(),
        "hard_constraint_eligible": bool(payload.get("hard_constraint_eligible")),
        "transform_required": payload.get("transform_required"),
      }
    )
  return audit


def _build_constraint_profile(
  *,
  fixed_facts: Dict[str, Any],
  controllable_drivers: Dict[str, Any],
  derived_outputs: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  baseline_payroll_support: float,
  fixed_people_payroll: float,
) -> Dict[str, Any]:
  revenue_drivers = controllable_drivers.get("revenue") if isinstance(controllable_drivers, dict) else {}
  marketing_drivers = controllable_drivers.get("marketing") if isinstance(controllable_drivers, dict) else {}
  opex_drivers = controllable_drivers.get("other_opex") if isinstance(controllable_drivers, dict) else {}
  people_drivers = controllable_drivers.get("people") if isinstance(controllable_drivers, dict) else {}
  constraint_basis = fixed_facts.get("constraint_basis") if isinstance(fixed_facts, dict) else {}

  price_driver = (revenue_drivers or {}).get("unit_price") if isinstance(revenue_drivers, dict) else {}
  util_driver = (revenue_drivers or {}).get("utilization_rate") if isinstance(revenue_drivers, dict) else {}
  marketing_driver = (marketing_drivers or {}).get("marketing_total_year1") if isinstance(marketing_drivers, dict) else {}
  opex_driver = (opex_drivers or {}).get("other_operating_expense") if isinstance(opex_drivers, dict) else {}
  inferred_roles = (people_drivers or {}).get("inferred_roles") if isinstance(people_drivers, dict) else []
  inferred_roles = inferred_roles if isinstance(inferred_roles, list) else []

  demand_supported_units_semantic = _constraint_source_value(constraint_basis, "demand_supported_units_year1")
  staffing_supported_capacity_semantic = _constraint_source_value(constraint_basis, "staffing_supported_capacity_units_year1")
  required_units_semantic = _semantic_value(
    value=max(0.0, _safe_float(fixed_facts.get("baseline_units_year1"))),
    metric_type="units",
    unit_basis="core_unit",
    time_basis="per_year",
    hard_constraint_eligible=True,
  )
  demand_curve: Dict[str, Any] = {
    "semantic": demand_supported_units_semantic,
    "baseline_supported_units": _semantic_value_number(demand_supported_units_semantic),
    "units_per_marketing_dollar": 0.0,
    "enabled": False,
  }
  marketing_baseline = max(0.0, _safe_float((marketing_driver or {}).get("baseline")))
  if (
    _semantic_values_compatible(required_units_semantic, demand_supported_units_semantic)
    and marketing_baseline > 0
  ):
    demand_curve["units_per_marketing_dollar"] = (
      _semantic_value_number(demand_supported_units_semantic) / max(marketing_baseline, 1e-9)
    )
    demand_curve["enabled"] = demand_curve["units_per_marketing_dollar"] > 0

  capacity_curve: Dict[str, Any] = {
    "semantic": staffing_supported_capacity_semantic,
    "baseline_supported_units": _semantic_value_number(staffing_supported_capacity_semantic),
    "units_per_payroll_dollar": 0.0,
    "baseline_payroll_support": max(0.0, baseline_payroll_support),
    "fixed_people_payroll": max(0.0, fixed_people_payroll),
    "units_per_active_role_month": 0.0,
    "fixed_active_role_months": 0.0,
    "baseline_adjustable_active_months": 0.0,
    "basis": "payroll",
    "enabled": False,
  }
  current_staff = fixed_facts.get("current_staff") if isinstance(fixed_facts, dict) else []
  current_staff = current_staff if isinstance(current_staff, list) else []
  fixed_active_role_months = 12.0 * float(len([p for p in current_staff if isinstance(p, dict)]))
  baseline_adjustable_active_months = 0.0
  for role in inferred_roles:
    if not isinstance(role, dict):
      continue
    base_months = max(0, min(12, _safe_int(role.get("base_months")) or 0))
    baseline_adjustable_active_months += max(0.0, 12.0 - float(base_months))
  total_active_role_months = fixed_active_role_months + baseline_adjustable_active_months
  if (
    _semantic_values_compatible(required_units_semantic, staffing_supported_capacity_semantic)
    and total_active_role_months > 0
  ):
    capacity_curve["units_per_active_role_month"] = (
      _semantic_value_number(staffing_supported_capacity_semantic) / max(total_active_role_months, 1e-9)
    )
    capacity_curve["fixed_active_role_months"] = fixed_active_role_months
    capacity_curve["baseline_adjustable_active_months"] = baseline_adjustable_active_months
    capacity_curve["basis"] = "role_months"
    capacity_curve["enabled"] = capacity_curve["units_per_active_role_month"] > 0
  elif (
    _semantic_values_compatible(required_units_semantic, staffing_supported_capacity_semantic)
    and baseline_payroll_support > 0
  ):
    capacity_curve["units_per_payroll_dollar"] = (
      _semantic_value_number(staffing_supported_capacity_semantic) / max(baseline_payroll_support, 1e-9)
    )
    capacity_curve["basis"] = "payroll"
    capacity_curve["enabled"] = capacity_curve["units_per_payroll_dollar"] > 0

  role_wage_bounds: List[Dict[str, Any]] = []
  for role in inferred_roles:
    if not isinstance(role, dict):
      continue
    role_wage_bounds.append(
      {
        "role_title": str(role.get("role_title") or "").strip(),
        "baseline": max(0.0, _safe_float(role.get("annual_wage"))),
        "min": max(0.0, _safe_float(role.get("wage_floor"))),
        "max": max(0.0, _safe_float(role.get("wage_ceiling"))),
      }
    )

  return {
    "required_units_semantic": required_units_semantic,
    "constraint_audit": _build_constraint_audit(constraint_basis or {}),
    "price_envelope": {
      "baseline": _safe_float((price_driver or {}).get("baseline")),
      "min": _safe_float((price_driver or {}).get("min")),
      "max": _safe_float((price_driver or {}).get("max")),
      "enabled": bool((price_driver or {}).get("enabled")),
    },
    "utilization_envelope": {
      "baseline": _normalize_ratio((util_driver or {}).get("baseline")) or 0.0,
      "min": _normalize_ratio((util_driver or {}).get("min")) or 0.0,
      "max": _normalize_ratio((util_driver or {}).get("max")) or 1.0,
      "enabled": bool((util_driver or {}).get("enabled")),
    },
    "marketing_envelope": {
      "baseline": marketing_baseline,
      "min": max(0.0, _safe_float((marketing_driver or {}).get("min"))),
      "max": max(0.0, _safe_float((marketing_driver or {}).get("max"))),
      "enabled": bool((marketing_driver or {}).get("enabled")),
      "source": str((marketing_driver or {}).get("source") or "").strip() or "parent_fallback",
    },
    "marketing_children": {
      "reachable_market": max(0.0, _safe_float((marketing_model_json or {}).get("reachable_market"))),
      "baseline_capture_rate": max(
        _safe_float((marketing_model_json or {}).get("capture_rate_year1")),
        (
          max(0.0, _safe_float(fixed_facts.get("baseline_units_year1")))
          / max(_safe_float((marketing_model_json or {}).get("reachable_market")), 1e-9)
          if _safe_float((marketing_model_json or {}).get("reachable_market")) > 0
          else 0.0
        ),
      ),
      "baseline_expected_customers_or_clients_year1": max(
        0.0,
        _safe_float((marketing_model_json or {}).get("expected_customers_or_clients_year1")),
      ),
      "baseline_expected_units_year1": max(
        0.0,
        _safe_float((marketing_model_json or {}).get("expected_units_year1")),
      ),
    },
    "other_opex_envelope": {
      "baseline": max(0.0, _safe_float((opex_driver or {}).get("baseline"))),
      "min": (
        max(0.0, _safe_float((opex_driver or {}).get("baseline")))
        if str((opex_driver or {}).get("source") or "").strip() == "parent_fallback"
        else max(0.0, _safe_float((opex_driver or {}).get("min")))
      ),
      "max": max(0.0, _safe_float((opex_driver or {}).get("max"))),
      "enabled": bool((opex_driver or {}).get("enabled")) and str((opex_driver or {}).get("source") or "").strip() != "parent_fallback",
      "source": str((opex_driver or {}).get("source") or "").strip() or "parent_fallback",
    },
    "demand_curve": demand_curve,
    "capacity_curve": capacity_curve,
    "role_wage_bounds": role_wage_bounds,
    "current_revenue": max(0.0, _safe_float((derived_outputs or {}).get("revenue"))),
    "current_cogs": max(0.0, _safe_float((fixed_facts or {}).get("cogs_total_year1"))),
    "current_interest": max(0.0, _safe_float((fixed_facts or {}).get("interest"))),
    "rent_annualized": max(0.0, _safe_float((fixed_facts or {}).get("rent_annualized"))),
  }


def _build_solver_state_model(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  baseline_summary: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  current_price = _safe_float(
    _top_level_driver_value(financials_year1_json or {}, "unit_price")
    or (ops_json or {}).get("unit_price")
  )
  current_util = _normalize_ratio(
    _top_level_driver_value(financials_year1_json or {}, "utilization_rate")
    or (ops_json or {}).get("utilization_rate")
  )
  baseline_units = _required_units_year1(financials_year1_json or {})
  if current_price <= 0 or current_util is None or current_util <= 0 or baseline_units <= 0:
    return None

  capacity_units = baseline_units / max(current_util, 1e-9)
  expected_units = max(
    0.0,
    _safe_float((marketing_model_json or {}).get("expected_units_year1")),
  )
  reachable_market = max(
    0.0,
    _safe_float((marketing_model_json or {}).get("reachable_market")),
  )
  current_marketing = max(0.0, _safe_float((financials_json or {}).get("marketing_total_year1")))
  current_other_opex = max(0.0, _safe_float((financials_json or {}).get("other_operating_expense")))
  current_interest = max(0.0, _safe_float((baseline_summary or {}).get("interest")))
  current_cogs = max(0.0, _safe_float((baseline_summary or {}).get("cogs")))
  rent_annualized = max(0.0, _safe_float((baseline_summary or {}).get("rent_annualized")))
  fixed_people_payroll = 0.0
  current_people: List[Dict[str, Any]] = []
  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    annual_wage = max(0.0, _safe_float(person.get("annual_wage")))
    fixed_people_payroll += annual_wage
    current_people.append(
      {
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "adjustable": False,
      }
    )

  planned_roles = _collect_solver_roles(people_json or {})
  baseline_planned_payroll = sum(_safe_float(role.get("baseline_year1_amount")) for role in planned_roles)
  baseline_payroll_support = fixed_people_payroll + baseline_planned_payroll
  baseline_gap = _ebitda_gap(baseline_summary)
  required_price_for_gap = current_price + (baseline_gap / max(1.0, baseline_units))
  marketing_upper = current_marketing
  if current_marketing > 0 and expected_units > 0:
    marketing_upper = current_marketing * max(1.0, capacity_units / expected_units)
  constraint_basis_payload = {
    "staffing_supported_capacity_units_year1": _semantic_value(
      value=capacity_units,
      metric_type="units",
      unit_basis="core_unit",
      time_basis="per_year",
      hard_constraint_eligible=True,
    ),
    "demand_supported_units_year1": _semantic_value(
      value=expected_units,
      metric_type="units",
      unit_basis="core_unit",
      time_basis="per_year",
      hard_constraint_eligible=True,
    ),
    "reachable_market": _semantic_value(
      value=reachable_market,
      metric_type="customers",
      unit_basis="potential_buyers",
      time_basis="point_in_time",
      hard_constraint_eligible=False,
      transform_required="convert_market_population_to_core_unit_demand",
    ),
  }
  controllable_drivers = {
    "revenue": {
      "unit_price": {
        "baseline": current_price,
        "min": current_price,
        "max": current_price,
        "enabled": ENABLE_PRICE_LEVER,
      },
      "utilization_rate": {
        "baseline": current_util,
        "min": current_util,
        "max": min(1.0, max(current_util, capacity_units / max(baseline_units, 1e-9))),
        "enabled": True,
      },
    },
    "marketing": {
      "marketing_total_year1": {
        "baseline": current_marketing,
        "min": 0.0,
        "max": max(current_marketing, marketing_upper),
        "enabled": True,
        "source": "parent_fallback",
      },
    },
    "other_opex": {
      "other_operating_expense": {
        "baseline": current_other_opex,
        "min": 0.0,
        "max": current_other_opex,
        "enabled": True,
        "source": "parent_fallback",
      },
    },
    "people": {
      "inferred_roles": [
        {
          "role_title": str(role.get("role_title") or "").strip(),
          "annual_wage": _safe_float(role.get("annual_wage")),
          "base_months": max(0, min(12, _safe_int(role.get("base_months")) or 0)),
          "baseline_year1_amount": max(0.0, _safe_float(role.get("baseline_year1_amount"))),
          "wage_floor": max(0.0, _safe_float(role.get("wage_floor"))),
          "wage_ceiling": max(0.0, _safe_float(role.get("wage_ceiling"))),
          "enabled": True,
        }
        for role in planned_roles
        if isinstance(role, dict)
      ],
    },
    "milestones": {
      "timing_months_max": [
        {
          "index": index,
          "baseline": int(max(1, _safe_int(milestone.get("timing_months_max")) or 1)),
        }
        for index, milestone in enumerate((ops_json or {}).get("milestones") or [])
        if isinstance(milestone, dict)
      ],
    },
  }
  derived_outputs = {
    "revenue": max(0.0, _safe_float((baseline_summary or {}).get("revenue"))),
    "gross_profit": max(0.0, _safe_float((baseline_summary or {}).get("gross_profit"))),
    "payroll_total_year1": max(0.0, _safe_float((baseline_summary or {}).get("payroll"))),
    "marketing_total_year1": current_marketing,
    "other_opex_total_year1": max(0.0, _safe_float((baseline_summary or {}).get("other_opex"))),
    "ebitda": _safe_float((baseline_summary or {}).get("ebitda")),
    "net_income": _safe_float((baseline_summary or {}).get("net_income")),
    "loss_pct": _loss_pct(baseline_summary),
    "break_even_gap": baseline_gap,
  }
  fixed_facts = {
    "capacity_driver": str((ops_json or {}).get("capacity_driver") or "").strip(),
    "current_staff": current_people,
    "rent_annualized": rent_annualized,
    "interest": current_interest,
    "cogs_total_year1": current_cogs,
    "reachable_market": reachable_market,
    "baseline_units_year1": baseline_units,
    "supported_capacity_units_year1": capacity_units,
    "expected_units_year1": expected_units,
    "constraint_basis": constraint_basis_payload,
    "constraint_audit": _build_constraint_audit(constraint_basis_payload),
  }
  constraint_profile = _build_constraint_profile(
    fixed_facts=fixed_facts,
    controllable_drivers=controllable_drivers,
    derived_outputs=derived_outputs,
    marketing_model_json=marketing_model_json,
    baseline_payroll_support=baseline_payroll_support,
    fixed_people_payroll=fixed_people_payroll,
  )

  return {
    "fixed_facts": fixed_facts,
    "controllable_drivers": controllable_drivers,
    "derived_outputs": derived_outputs,
    "constraint_profile": constraint_profile,
    "objective_policy": {
      "primary_target": "ebitda_break_even",
      "fallback_target": "minimize_ebitda_gap",
      "healthy_ebitda_margin_ratio": HEALTHY_EBITDA_MARGIN_RATIO,
      "ebitda_cushion_preference_weight": EBITDA_CUSHION_PREFERENCE_WEIGHT,
      "option_objective_tolerance_ratio": OPTION_OBJECTIVE_TOLERANCE_RATIO,
      "option_objective_tolerance_abs": OPTION_OBJECTIVE_TOLERANCE_ABS,
      "family_concentration_weight": FAMILY_CONCENTRATION_WEIGHT,
      "distortion_weights": {
        "price_up": PRICE_DISTORTION_WEIGHT,
        "util_up": UTILIZATION_DISTORTION_WEIGHT,
        "marketing_up": MARKETING_UP_DISTORTION_WEIGHT,
        "marketing_down": MARKETING_DOWN_DISTORTION_WEIGHT,
        "other_opex_down": OTHER_OPEX_DISTORTION_WEIGHT,
        "hire_delay": HIRE_DELAY_DISTORTION_WEIGHT,
        "payroll_down": PAYROLL_DOWN_DISTORTION_WEIGHT,
      },
    },
  }


def _solver_profiles(state_model: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  base_weights = {}
  family_concentration_weight = FAMILY_CONCENTRATION_WEIGHT
  ebitda_cushion_preference_weight = EBITDA_CUSHION_PREFERENCE_WEIGHT
  objective_tolerance_ratio = OPTION_OBJECTIVE_TOLERANCE_RATIO
  objective_tolerance_abs = OPTION_OBJECTIVE_TOLERANCE_ABS
  if isinstance(state_model, dict):
    objective_policy = state_model.get("objective_policy")
    if isinstance(objective_policy, dict):
      maybe_weights = objective_policy.get("distortion_weights")
      if isinstance(maybe_weights, dict):
        base_weights = dict(maybe_weights)
      family_concentration_weight = _safe_float(
        objective_policy.get("family_concentration_weight"),
      ) or FAMILY_CONCENTRATION_WEIGHT
      ebitda_cushion_preference_weight = _safe_float(
        objective_policy.get("ebitda_cushion_preference_weight"),
      ) or EBITDA_CUSHION_PREFERENCE_WEIGHT
      objective_tolerance_ratio = _safe_float(
        objective_policy.get("option_objective_tolerance_ratio"),
      ) or OPTION_OBJECTIVE_TOLERANCE_RATIO
      objective_tolerance_abs = _safe_float(
        objective_policy.get("option_objective_tolerance_abs"),
      ) or OPTION_OBJECTIVE_TOLERANCE_ABS
  if not base_weights:
    base_weights = {
      "price_up": PRICE_DISTORTION_WEIGHT,
      "util_up": UTILIZATION_DISTORTION_WEIGHT,
      "marketing_up": MARKETING_UP_DISTORTION_WEIGHT,
      "marketing_down": MARKETING_DOWN_DISTORTION_WEIGHT,
      "other_opex_down": OTHER_OPEX_DISTORTION_WEIGHT,
      "hire_delay": HIRE_DELAY_DISTORTION_WEIGHT,
      "payroll_down": PAYROLL_DOWN_DISTORTION_WEIGHT,
    }

  def profile_with(
    profile_id: str,
    overrides: Dict[str, float],
    *,
    constraints: Optional[Dict[str, float]] = None,
    anchor_strict: bool = False,
  ) -> Dict[str, Any]:
    weights = dict(base_weights)
    for key, factor in overrides.items():
      weights[key] = _safe_float(weights.get(key)) * _safe_float(factor)
    return {
      "profile_id": profile_id,
      "weights": weights,
      "constraints": dict(constraints or {}),
      "family_concentration_weight": family_concentration_weight,
      "ebitda_cushion_preference_weight": ebitda_cushion_preference_weight,
      "objective_tolerance_ratio": objective_tolerance_ratio,
      "objective_tolerance_abs": objective_tolerance_abs,
      "anchor_strict": bool(anchor_strict),
    }

  return [
    profile_with("balanced", {}, anchor_strict=True),
    profile_with(
      "growth_first",
      {
        "marketing_up": 0.55,
        "util_up": 0.65,
        "marketing_down": 1.5,
        "other_opex_down": 1.15,
        "hire_delay": 1.35,
        "payroll_down": 1.35,
      },
      constraints={
        "marketing_min_ratio": 0.95,
      },
    ),
    profile_with(
      "profit_first",
      {
        "marketing_up": 1.35,
        "util_up": 1.1,
        "marketing_down": 0.8,
        "other_opex_down": 0.7,
        "hire_delay": 0.9,
        "payroll_down": 0.7,
      },
      constraints={
        "marketing_max_ratio": 1.05,
      },
    ),
    profile_with(
      "lean_survival",
      {
        "marketing_up": 1.6,
        "util_up": 1.25,
        "marketing_down": 0.7,
        "other_opex_down": 0.7,
        "hire_delay": 0.65,
        "payroll_down": 0.6,
      },
      constraints={
        "marketing_max_ratio": 1.0,
      },
    ),
  ]


def _build_direct_solver_inputs(
  *,
  state_model: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  fixed_facts = state_model.get("fixed_facts") if isinstance(state_model, dict) else {}
  controllable = state_model.get("controllable_drivers") if isinstance(state_model, dict) else {}
  constraint_profile = state_model.get("constraint_profile") if isinstance(state_model, dict) else {}
  people_drivers = (controllable or {}).get("people") if isinstance(controllable, dict) else {}
  price_envelope = (constraint_profile or {}).get("price_envelope") if isinstance(constraint_profile, dict) else {}
  util_envelope = (constraint_profile or {}).get("utilization_envelope") if isinstance(constraint_profile, dict) else {}
  marketing_envelope = (constraint_profile or {}).get("marketing_envelope") if isinstance(constraint_profile, dict) else {}
  other_opex_envelope = (constraint_profile or {}).get("other_opex_envelope") if isinstance(constraint_profile, dict) else {}
  capacity_curve = (constraint_profile or {}).get("capacity_curve") if isinstance(constraint_profile, dict) else {}
  demand_curve = (constraint_profile or {}).get("demand_curve") if isinstance(constraint_profile, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}

  current_price = _safe_float((price_envelope or {}).get("baseline"))
  current_util = _normalize_ratio((util_envelope or {}).get("baseline"))
  if current_price <= 0 or current_util is None or current_util <= 0:
    return None

  baseline_units = max(0.0, _safe_float((fixed_facts or {}).get("baseline_units_year1")))
  if baseline_units <= 0:
    return None

  capacity_units = max(0.0, _safe_float((fixed_facts or {}).get("supported_capacity_units_year1")))
  fixed_people_payroll = 0.0
  for person in (fixed_facts or {}).get("current_staff") or []:
    if not isinstance(person, dict):
      continue
    fixed_people_payroll += max(0.0, _safe_float(person.get("annual_wage")))

  roles = (people_drivers or {}).get("inferred_roles") if isinstance(people_drivers, dict) else []
  roles = roles if isinstance(roles, list) else []
  baseline_planned_payroll = sum(_safe_float(role.get("baseline_year1_amount")) for role in roles)
  baseline_payroll_support = max(
    fixed_people_payroll + baseline_planned_payroll,
    _safe_float((capacity_curve or {}).get("baseline_payroll_support")),
  )

  return {
    "current_price": current_price,
    "price_enabled": bool((price_envelope or {}).get("enabled")),
    "current_util": current_util,
    "util_min": _normalize_ratio((util_envelope or {}).get("min")) or current_util,
    "util_max": _normalize_ratio((util_envelope or {}).get("max")) or 1.0,
    "baseline_units": baseline_units,
    "capacity_units": capacity_units,
    "current_marketing": max(0.0, _safe_float((marketing_envelope or {}).get("baseline"))),
    "marketing_min": max(0.0, _safe_float((marketing_envelope or {}).get("min"))),
    "marketing_upper": max(0.0, _safe_float((marketing_envelope or {}).get("max"))),
    "marketing_support_units_baseline": max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1"))),
    "marketing_support_units_max": max(
      0.0,
      _safe_float((demand_curve or {}).get("units_per_marketing_dollar")) * max(0.0, _safe_float((marketing_envelope or {}).get("max"))),
    ),
    "marketing_units_per_dollar": max(0.0, _safe_float((demand_curve or {}).get("units_per_marketing_dollar"))),
    "current_other_opex": max(0.0, _safe_float((other_opex_envelope or {}).get("baseline"))),
    "other_opex_min": max(0.0, _safe_float((other_opex_envelope or {}).get("min"))),
    "other_opex_enabled": bool((other_opex_envelope or {}).get("enabled")),
    "fixed_people_payroll": fixed_people_payroll,
    "baseline_planned_payroll": baseline_planned_payroll,
    "baseline_payroll_support": baseline_payroll_support,
    "roles": roles,
    "constraint_profile": constraint_profile,
    "expected_units": max(0.0, _safe_float((demand_curve or {}).get("baseline_supported_units"))),
    "required_units_semantic": (constraint_profile or {}).get("required_units_semantic"),
    "staffing_supported_capacity_semantic": (capacity_curve or {}).get("semantic"),
    "demand_supported_units_semantic": (demand_curve or {}).get("semantic"),
    "reachable_market_semantic": _constraint_source_value(
      (fixed_facts or {}).get("constraint_basis") if isinstance(fixed_facts, dict) else {},
      "reachable_market",
    ),
    "current_revenue": max(0.0, _safe_float((constraint_profile or {}).get("current_revenue"))),
    "current_cogs": max(0.0, _safe_float((constraint_profile or {}).get("current_cogs"))),
    "current_interest": max(0.0, _safe_float((constraint_profile or {}).get("current_interest"))),
    "current_other_opex_total": max(
      0.0,
      _safe_float((constraint_profile or {}).get("current_other_opex_total") or (state_model.get("derived_outputs") or {}).get("other_opex_total_year1")),
    ),
    "rent_annualized": max(0.0, _safe_float((constraint_profile or {}).get("rent_annualized"))),
    "price_upper": max(current_price, _safe_float((price_envelope or {}).get("max"))),
  }


def _label_and_rationale_from_patches(exact_patches: Dict[str, Any]) -> Tuple[str, str, List[str]]:
  label_parts: List[str] = []
  rationale_parts: List[str] = []
  families: List[str] = []

  year1_patch = exact_patches.get("financials_year1_patch")
  if isinstance(year1_patch, dict):
    if year1_patch.get("unit_price") is not None:
      families.append("price")
      label_parts.append(f"Increase price to {_format_currency(year1_patch.get('unit_price'))}")
      rationale_parts.append("raise pricing")
    if year1_patch.get("utilization_rate") is not None:
      families.append("utilization")
      label_parts.append(f"Increase utilization to {_format_percent(year1_patch.get('utilization_rate'))}")
      rationale_parts.append("fill more of the existing capacity")

  financials_patch = exact_patches.get("financials_patch")
  if isinstance(financials_patch, dict):
    if financials_patch.get("marketing_total_year1") is not None:
      target = _safe_float(financials_patch.get("marketing_total_year1"))
      families.append("marketing")
      label_parts.append(f"Set Year-1 marketing to {_format_currency(target)}")
      rationale_parts.append("reset the Year-1 marketing ramp")
    if financials_patch.get("other_operating_expense") is not None:
      target = _safe_float(financials_patch.get("other_operating_expense"))
      families.append("other_opex")
      label_parts.append(f"Reduce other operating expense to {_format_currency(target)}")
      rationale_parts.append("tighten non-rent operating spend")
  marketing_model_patch = exact_patches.get("marketing_model_patch")
  if isinstance(marketing_model_patch, dict):
    expected_units = _safe_float(marketing_model_patch.get("expected_units_year1"))
    if expected_units > 0:
      families.append("marketing")
      label_parts.append(f"Reset marketing support to {expected_units:,.0f} Year-1 units")
      rationale_parts.append("rebuild the marketing support level behind Year-1 demand")

  role_updates = exact_patches.get("people_role_updates")
  if isinstance(role_updates, list):
    for update in role_updates:
      if not isinstance(update, dict):
        continue
      role_title = str(update.get("role_title") or "").strip()
      months = _safe_int(update.get("months_until_hire"))
      if not role_title or months is None:
        continue
      families.append("hire_delay")
      label_parts.append(f"Delay {role_title} to month {months}")
      rationale_parts.append(f"push {role_title} later in Year 1")
      if update.get("annual_wage") is not None and _safe_float(update.get("annual_wage")) > 0:
        families.append("payroll")
        label_parts.append(f"Set {role_title} pay to {_format_currency(update.get('annual_wage'))}/year")
        rationale_parts.append(f"use a leaner Year-1 pay level for {role_title}")

  label = " + ".join(label_parts)
  rationale = "This path " + ", ".join(rationale_parts) + "."
  if not label:
    label = "Keep the current plan"
  if not rationale_parts:
    rationale = "This path keeps the current Year-1 plan intact."
  return label, rationale, list(dict.fromkeys(families))


def _build_candidate_from_exact_patches(
  *,
  scenario_id: str,
  baseline_summary: Dict[str, Any],
  baseline_state: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  exact_patches: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  label, rationale, families = _label_and_rationale_from_patches(exact_patches)
  return _build_candidate(
    scenario_id=scenario_id,
    baseline_summary=baseline_summary,
    baseline_state=baseline_state,
    marketing_model_json=marketing_model_json,
    label=label,
    rationale=rationale,
    lever_families=families,
    exact_patches=exact_patches,
  )


def _archetype_preference_objective(
  *,
  profile_id: str,
  max_family_move: Any,
  price_move: Any,
  util_move: Any,
  marketing_up_move: Any,
  marketing_down_move: Any,
  opex_down_move: Any,
  hire_delay_move: Any,
  payroll_down_move: Any,
  ebitda_expr: Any,
  revenue_scale: float,
):
  normalized_ebitda = ebitda_expr / max(revenue_scale, 1.0)
  if profile_id == "growth_first":
    return (
      1.0 * max_family_move
      - 1.25 * util_move
      - 1.15 * marketing_up_move
      + 0.85 * marketing_down_move
      + 0.75 * hire_delay_move
      + 0.75 * payroll_down_move
      + 0.35 * opex_down_move
      - 0.35 * normalized_ebitda
    )
  if profile_id == "profit_first":
    return (
      0.95 * max_family_move
      - 0.95 * payroll_down_move
      - 0.8 * opex_down_move
      - 0.45 * marketing_down_move
      + 0.85 * marketing_up_move
      + 0.35 * util_move
      + 0.3 * hire_delay_move
      - 0.5 * normalized_ebitda
    )
  if profile_id == "lean_survival":
    return (
      0.9 * max_family_move
      - 1.0 * hire_delay_move
      - 0.95 * payroll_down_move
      - 0.65 * marketing_down_move
      - 0.35 * opex_down_move
      + 1.0 * marketing_up_move
      + 0.55 * util_move
      - 0.25 * normalized_ebitda
    )
  return (
    1.15 * max_family_move
    - 0.45 * util_move
    - 0.4 * marketing_up_move
    - 0.35 * payroll_down_move
    - 0.3 * hire_delay_move
    - 0.2 * opex_down_move
    + 0.15 * price_move
    - 0.3 * normalized_ebitda
  )


def _solve_direct_profile(
  *,
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  target_ebitda_min: Optional[float],
  family_caps: Optional[Dict[str, float]] = None,
):
  pulp = _require_pulp()
  problem = pulp.LpProblem(f"consistency_solver_{profile.get('profile_id')}", pulp.LpMinimize)
  weights = profile.get("weights") if isinstance(profile, dict) else {}
  weights = weights if isinstance(weights, dict) else {}
  profile_constraints = profile.get("constraints") if isinstance(profile, dict) else {}
  profile_constraints = profile_constraints if isinstance(profile_constraints, dict) else {}
  family_concentration_weight = (
    _safe_float(profile.get("family_concentration_weight"))
    if isinstance(profile, dict)
    else 0.0
  )
  ebitda_cushion_preference_weight = (
    _safe_float(profile.get("ebitda_cushion_preference_weight"))
    if isinstance(profile, dict)
    else 0.0
  )
  objective_tolerance_ratio = (
    max(0.0, _safe_float(profile.get("objective_tolerance_ratio")))
    if isinstance(profile, dict)
    else 0.0
  )
  objective_tolerance_abs = (
    max(0.0, _safe_float(profile.get("objective_tolerance_abs")))
    if isinstance(profile, dict)
    else 0.0
  )
  anchor_strict = bool(profile.get("anchor_strict")) if isinstance(profile, dict) else False

  current_price = _safe_float(direct_inputs.get("current_price"))
  price_enabled = bool(direct_inputs.get("price_enabled"))
  price_upper = max(current_price, _safe_float(direct_inputs.get("price_upper")))
  current_util = _normalize_ratio(direct_inputs.get("current_util")) or 0.0
  util_max = max(current_util, _normalize_ratio(direct_inputs.get("util_max")) or 1.0)
  current_marketing = max(0.0, _safe_float(direct_inputs.get("current_marketing")))
  marketing_min = max(0.0, _safe_float(direct_inputs.get("marketing_min")))
  marketing_upper = max(current_marketing, _safe_float(direct_inputs.get("marketing_upper")))
  marketing_support_units_baseline = max(0.0, _safe_float(direct_inputs.get("marketing_support_units_baseline")))
  marketing_support_units_max = max(marketing_support_units_baseline, _safe_float(direct_inputs.get("marketing_support_units_max")))
  marketing_units_per_dollar = max(0.0, _safe_float(direct_inputs.get("marketing_units_per_dollar")))
  current_other_opex = max(0.0, _safe_float(direct_inputs.get("current_other_opex")))
  other_opex_min = max(0.0, _safe_float(direct_inputs.get("other_opex_min")))
  other_opex_enabled = bool(direct_inputs.get("other_opex_enabled"))
  current_cogs = max(0.0, _safe_float(direct_inputs.get("current_cogs")))
  current_interest = max(0.0, _safe_float(direct_inputs.get("current_interest")))
  rent_annualized = max(0.0, _safe_float(direct_inputs.get("rent_annualized")))
  capacity_units = max(0.0, _safe_float(direct_inputs.get("capacity_units")))
  expected_units = max(0.0, _safe_float(direct_inputs.get("expected_units")))
  required_units_semantic = direct_inputs.get("required_units_semantic")
  staffing_supported_capacity_semantic = direct_inputs.get("staffing_supported_capacity_semantic")
  demand_supported_units_semantic = direct_inputs.get("demand_supported_units_semantic")
  reachable_market_semantic = direct_inputs.get("reachable_market_semantic")
  constraint_profile = direct_inputs.get("constraint_profile") if isinstance(direct_inputs, dict) else {}
  capacity_curve = (constraint_profile or {}).get("capacity_curve") if isinstance(constraint_profile, dict) else {}
  demand_curve = (constraint_profile or {}).get("demand_curve") if isinstance(constraint_profile, dict) else {}
  fixed_people_payroll = max(0.0, _safe_float(direct_inputs.get("fixed_people_payroll")))
  baseline_payroll_support = max(0.0, _safe_float(direct_inputs.get("baseline_payroll_support")))
  roles = direct_inputs.get("roles") if isinstance(direct_inputs, dict) else []
  roles = roles if isinstance(roles, list) else []

  price = pulp.LpVariable("price", lowBound=current_price, upBound=(current_price if not price_enabled else price_upper), cat="Continuous")
  util = pulp.LpVariable("util", lowBound=current_util, upBound=util_max, cat="Continuous")
  if marketing_units_per_dollar > 0:
    marketing_support_units = pulp.LpVariable(
      "marketing_support_units",
      lowBound=marketing_support_units_baseline,
      upBound=marketing_support_units_max,
      cat="Continuous",
    )
    marketing_expr = marketing_support_units / marketing_units_per_dollar
  else:
    marketing_support_units = pulp.LpVariable(
      "marketing_support_units",
      lowBound=marketing_support_units_baseline,
      upBound=marketing_support_units_baseline,
      cat="Continuous",
    )
    marketing_expr = current_marketing
  other_opex = pulp.LpVariable(
    "other_opex",
    lowBound=(other_opex_min if other_opex_enabled else current_other_opex),
    upBound=current_other_opex,
    cat="Continuous",
  )
  price_util = pulp.LpVariable("price_util", lowBound=current_price * current_util, upBound=price_upper, cat="Continuous")

  # McCormick envelope for z = price * util.
  price_lb = current_price
  price_ub = price_upper
  util_lb = current_util
  util_ub = 1.0
  problem += price_util >= price_lb * util + util_lb * price - (price_lb * util_lb)
  problem += price_util >= price_ub * util + util_ub * price - (price_ub * util_ub)
  problem += price_util <= price_lb * util + util_ub * price - (price_lb * util_ub)
  problem += price_util <= price_ub * util + util_lb * price - (price_ub * util_lb)

  role_month_vars: Dict[str, Any] = {}
  role_payroll_vars: Dict[str, Any] = {}
  role_wage_meta: Dict[str, Dict[str, float]] = {}
  payroll_terms: List[Any] = []
  total_delay_expr = 0
  total_payroll_down_expr = 0
  for index, role in enumerate(roles):
    role_title = str(role.get("role_title") or "").strip()
    base_months = max(0, min(12, _safe_int(role.get("base_months")) or 0))
    annual_wage = max(0.0, _safe_float(role.get("annual_wage")))
    wage_floor = max(0.0, _safe_float(role.get("wage_floor")) or annual_wage)
    wage_ceiling = max(wage_floor, _safe_float(role.get("wage_ceiling")) or annual_wage)
    baseline_year1_amount = max(0.0, _safe_float(role.get("baseline_year1_amount")))
    if not role_title or annual_wage <= 0:
      continue
    month_var = pulp.LpVariable(
      f"role_month_{index}",
      lowBound=base_months,
      upBound=12,
      cat="Integer",
    )
    payroll_var = pulp.LpVariable(
      f"role_payroll_{index}",
      lowBound=0.0,
      upBound=(wage_ceiling * 12.0 / 12.0),
      cat="Continuous",
    )
    role_month_vars[role_title] = month_var
    role_payroll_vars[role_title] = payroll_var
    role_wage_meta[role_title] = {
      "annual_wage": annual_wage,
      "wage_floor": wage_floor,
      "wage_ceiling": wage_ceiling,
      "baseline_year1_amount": baseline_year1_amount,
      "base_months": float(base_months),
    }
    active_months_expr = 12 - month_var
    problem += payroll_var >= (wage_floor / 12.0) * active_months_expr
    problem += payroll_var <= (wage_ceiling / 12.0) * active_months_expr
    payroll_terms.append(payroll_var)
    total_delay_expr += month_var - base_months
    if baseline_year1_amount > 0:
      total_payroll_down_expr += (baseline_year1_amount - payroll_var) / baseline_year1_amount
  role_count = max(len(role_payroll_vars), 1)

  payroll_expr = fixed_people_payroll + pulp.lpSum(payroll_terms)
  units_expr = capacity_units * util
  revenue_expr = capacity_units * price_util
  ebitda_expr = revenue_expr - current_cogs - payroll_expr - marketing_expr - other_opex - rent_annualized
  net_income_expr = ebitda_expr - current_interest
  revenue_scale = max(1.0, _safe_float(direct_inputs.get("current_revenue")) or (capacity_units * max(current_price, 1.0)))

  capacity_basis = str((capacity_curve or {}).get("basis") or "").strip().lower()
  capacity_units_per_role_month = max(0.0, _safe_float((capacity_curve or {}).get("units_per_active_role_month")))
  capacity_units_per_payroll = max(0.0, _safe_float((capacity_curve or {}).get("units_per_payroll_dollar")))
  if bool((capacity_curve or {}).get("enabled")) and capacity_basis == "role_months" and capacity_units_per_role_month > 0:
    fixed_active_role_months = max(0.0, _safe_float((capacity_curve or {}).get("fixed_active_role_months")))
    adjustable_active_role_months_expr = pulp.lpSum(12 - month_var for month_var in role_month_vars.values())
    staffing_supported_units = capacity_units_per_role_month * (fixed_active_role_months + adjustable_active_role_months_expr)
    problem += units_expr <= staffing_supported_units
  elif bool((capacity_curve or {}).get("enabled")) and capacity_units_per_payroll > 0:
    staffing_supported_units = capacity_units_per_payroll * payroll_expr
    problem += units_expr <= staffing_supported_units

  demand_units_per_marketing = max(0.0, _safe_float((demand_curve or {}).get("units_per_marketing_dollar")))
  if bool((demand_curve or {}).get("enabled")) and demand_units_per_marketing > 0:
    problem += units_expr <= marketing_support_units
  elif _semantic_values_compatible(required_units_semantic, demand_supported_units_semantic):
    demand_supported_units = _semantic_value_number(demand_supported_units_semantic)
    if demand_supported_units > 0:
      if current_marketing > 0:
        problem += units_expr <= demand_supported_units * (marketing_expr / max(current_marketing, 1e-9))
      else:
        problem += units_expr <= demand_supported_units
  if _semantic_values_compatible(required_units_semantic, reachable_market_semantic):
    reachable_market = _semantic_value_number(reachable_market_semantic)
    if reachable_market > 0:
      problem += units_expr <= reachable_market
  marketing_min_ratio = _safe_float(profile_constraints.get("marketing_min_ratio"))
  if current_marketing > 0 and marketing_min_ratio > 0:
    problem += marketing_expr >= current_marketing * marketing_min_ratio
  marketing_max_ratio = _safe_float(profile_constraints.get("marketing_max_ratio"))
  if current_marketing > 0 and marketing_max_ratio > 0:
    problem += marketing_expr <= current_marketing * marketing_max_ratio
  payroll_down_max_ratio = _safe_float(profile_constraints.get("payroll_down_max_ratio"))
  if payroll_down_max_ratio > 0:
    problem += total_payroll_down_expr <= payroll_down_max_ratio
  hire_delay_max_months_total = _safe_float(profile_constraints.get("hire_delay_max_months_total"))
  if hire_delay_max_months_total > 0:
    problem += total_delay_expr <= hire_delay_max_months_total

  shortfall = None
  target_ebitda_min = None if target_ebitda_min is None else float(target_ebitda_min)
  if target_ebitda_min is not None:
    problem += ebitda_expr >= target_ebitda_min
  else:
    shortfall = pulp.LpVariable("ebitda_shortfall", lowBound=0.0, cat="Continuous")
    problem += shortfall >= -ebitda_expr

  marketing_up = pulp.LpVariable("marketing_up", lowBound=0.0, cat="Continuous")
  marketing_down = pulp.LpVariable("marketing_down", lowBound=0.0, cat="Continuous")
  problem += marketing_expr - current_marketing == marketing_up - marketing_down

  price_move = (price - current_price) / max(current_price, 1.0) if price_enabled else 0.0
  util_move = (util - current_util) / max(1.0 - current_util, 1e-6)
  marketing_up_move = marketing_up / max(marketing_upper or 1.0, 1.0)
  marketing_down_move = marketing_down / max(current_marketing or 1.0, 1.0)
  opex_down_move = (current_other_opex - other_opex) / max(current_other_opex or 1.0, 1.0)
  payroll_down_move = total_payroll_down_expr / float(role_count)
  hire_delay_move = total_delay_expr / (12.0 * float(role_count))
  max_family_move = pulp.LpVariable("max_family_move", lowBound=0.0, cat="Continuous")
  for expr in (
    price_move,
    util_move,
    marketing_up_move,
    marketing_down_move,
    opex_down_move,
    payroll_down_move,
    hire_delay_move,
  ):
    if isinstance(expr, (int, float)):
      continue
    problem += max_family_move >= expr
  family_caps = family_caps if isinstance(family_caps, dict) else {}
  family_exprs = {
    "price_up": price_move,
    "util_up": util_move,
    "marketing_up": marketing_up_move,
    "marketing_down": marketing_down_move,
    "other_opex_down": opex_down_move,
    "hire_delay": hire_delay_move,
    "payroll_down": payroll_down_move,
  }
  for family_name, family_cap in family_caps.items():
    expr = family_exprs.get(str(family_name))
    if expr is None or isinstance(expr, (int, float)):
      continue
    cap_value = max(0.0, _safe_float(family_cap))
    problem += expr <= cap_value

  distortion_expr = (
    _safe_float(weights.get("price_up")) * ((price - current_price) / max(current_price, 1.0))
    + _safe_float(weights.get("util_up")) * ((util - current_util) / max(1.0 - current_util, 1e-6))
    + _safe_float(weights.get("marketing_up")) * (marketing_up / max(marketing_upper or 1.0, 1.0))
    + _safe_float(weights.get("marketing_down")) * (marketing_down / max(current_marketing or 1.0, 1.0))
    + _safe_float(weights.get("other_opex_down")) * ((current_other_opex - other_opex) / max(current_other_opex or 1.0, 1.0))
    + _safe_float(weights.get("hire_delay")) * hire_delay_move
    + _safe_float(weights.get("payroll_down")) * payroll_down_move
  )
  solver = pulp.PULP_CBC_CMD(msg=False)

  if shortfall is not None:
    problem.setObjective(shortfall)
  else:
    problem.setObjective(max_family_move)
  status = problem.solve(solver)
  if status != pulp.LpStatusOptimal:
    return None

  optimal_shortfall = float(shortfall.value() or 0.0) if shortfall is not None else 0.0
  if target_ebitda_min is not None:
    optimal_max_family_move = float(max_family_move.value() or 0.0)
  else:
    problem += shortfall <= (optimal_shortfall + 1e-6)
    problem.setObjective(max_family_move)
    status = problem.solve(solver)
    if status != pulp.LpStatusOptimal:
      return None
    optimal_max_family_move = float(max_family_move.value() or 0.0)
  problem += max_family_move <= (optimal_max_family_move + 1e-6)

  final_objective = distortion_expr
  if family_concentration_weight > 0:
    final_objective = final_objective + (family_concentration_weight * max_family_move)
  if ebitda_cushion_preference_weight > 0:
    final_objective = final_objective - (
      ebitda_cushion_preference_weight * (ebitda_expr / revenue_scale)
    )
  problem.setObjective(final_objective)
  status = problem.solve(solver)
  if status != pulp.LpStatusOptimal:
    return None
  optimal_final_objective = float(final_objective.value() or 0.0)

  if not anchor_strict:
    objective_tolerance = max(
      objective_tolerance_abs,
      abs(optimal_final_objective) * objective_tolerance_ratio,
    )
    if objective_tolerance > 0:
      problem += final_objective <= (optimal_final_objective + objective_tolerance)
    archetype_objective = _archetype_preference_objective(
      profile_id=str(profile.get("profile_id") or "").strip(),
      max_family_move=max_family_move,
      price_move=price_move,
      util_move=util_move,
      marketing_up_move=marketing_up_move,
      marketing_down_move=marketing_down_move,
      opex_down_move=opex_down_move,
      hire_delay_move=hire_delay_move,
      payroll_down_move=payroll_down_move,
      ebitda_expr=ebitda_expr,
      revenue_scale=revenue_scale,
    )
    problem.setObjective(archetype_objective)
    status = problem.solve(solver)
    if status != pulp.LpStatusOptimal:
      return None

  role_month_values = {
    role_title: int(round(float(month_var.value() or 0.0)))
    for role_title, month_var in role_month_vars.items()
  }
  role_payroll_values = {
    role_title: round(float(payroll_var.value() or 0.0), 2)
    for role_title, payroll_var in role_payroll_vars.items()
  }
  distortion_components = {
    "price_up": _safe_float(weights.get("price_up")) * max(0.0, (float(price.value() or current_price) - current_price) / max(current_price, 1.0)),
    "util_up": _safe_float(weights.get("util_up")) * max(0.0, (float(util.value() or current_util) - current_util) / max(1.0 - current_util, 1e-6)),
    "marketing_up": _safe_float(weights.get("marketing_up")) * max(0.0, float(marketing_up.value() or 0.0) / max(marketing_upper or 1.0, 1.0)),
    "marketing_down": _safe_float(weights.get("marketing_down")) * max(0.0, float(marketing_down.value() or 0.0) / max(current_marketing or 1.0, 1.0)),
    "other_opex_down": _safe_float(weights.get("other_opex_down")) * max(0.0, (current_other_opex - float(other_opex.value() or current_other_opex)) / max(current_other_opex or 1.0, 1.0)),
    "hire_delay": _safe_float(weights.get("hire_delay")) * max(0.0, float(total_delay_expr.value() or 0.0) / (12.0 * float(role_count))),
    "payroll_down": _safe_float(weights.get("payroll_down")) * max(0.0, float(total_payroll_down_expr.value() or 0.0) / float(role_count)),
  }
  family_raw_components = {
    "price_up": max(0.0, (float(price.value() or current_price) - current_price) / max(current_price, 1.0)) if price_enabled else 0.0,
    "util_up": max(0.0, (float(util.value() or current_util) - current_util) / max(1.0 - current_util, 1e-6)),
    "marketing_up": max(0.0, float(marketing_up.value() or 0.0) / max(marketing_upper or 1.0, 1.0)),
    "marketing_down": max(0.0, float(marketing_down.value() or 0.0) / max(current_marketing or 1.0, 1.0)),
    "other_opex_down": max(0.0, (current_other_opex - float(other_opex.value() or current_other_opex)) / max(current_other_opex or 1.0, 1.0)),
    "hire_delay": max(0.0, float(total_delay_expr.value() or 0.0) / (12.0 * float(role_count))),
    "payroll_down": max(0.0, float(total_payroll_down_expr.value() or 0.0) / float(role_count)),
  }
  return {
    "profile_id": str(profile.get("profile_id") or "").strip() or "profile",
    "target_ebitda_min": target_ebitda_min,
    "threshold_feasible": target_ebitda_min is not None,
    "anchor_strict": anchor_strict,
    "objective_tolerance_ratio": objective_tolerance_ratio,
    "price": round(float(price.value() or current_price), 2),
    "utilization_rate": float(util.value() or current_util),
    "marketing_total_year1": round(_safe_float(marketing_expr.value()) or current_marketing, 2),
    "marketing_support_units_year1": round(float(marketing_support_units.value() or marketing_support_units_baseline), 2),
    "other_operating_expense": round(float(other_opex.value() or current_other_opex), 2),
    "role_months": role_month_values,
    "role_year1_payroll": role_payroll_values,
    "role_wage_meta": role_wage_meta,
    "distortion_components": distortion_components,
    "distortion_total": sum(distortion_components.values()),
    "family_raw_components": family_raw_components,
    "max_family_move": float(max_family_move.value() or 0.0),
    "final_objective_value": float(final_objective.value() or 0.0),
    "optimal_final_objective": optimal_final_objective,
    "ebitda": float(ebitda_expr.value() or 0.0),
    "net_income": float(net_income_expr.value() or 0.0),
    "shortfall": optimal_shortfall,
  }


def _exact_patches_from_solution(
  *,
  solution: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Dict[str, Any]:
  exact_patches: Dict[str, Any] = {}
  financials_year1_patch: Dict[str, Any] = {}
  financials_patch: Dict[str, Any] = {}
  marketing_model_patch: Dict[str, Any] = {}
  people_role_updates: List[Dict[str, Any]] = []

  current_price = _safe_float(direct_inputs.get("current_price"))
  current_util = _normalize_ratio(direct_inputs.get("current_util")) or 0.0
  current_marketing = _safe_float(direct_inputs.get("current_marketing"))
  marketing_support_units_baseline = _safe_float(direct_inputs.get("marketing_support_units_baseline"))
  current_other_opex = _safe_float(direct_inputs.get("current_other_opex"))

  target_price = round(_safe_float(solution.get("price")), 2)
  if target_price > 0 and abs(target_price - current_price) >= 0.01:
    financials_year1_patch["unit_price"] = target_price

  target_util = _normalize_ratio(solution.get("utilization_rate"))
  if target_util is not None and abs(target_util - current_util) >= 0.0005:
    financials_year1_patch["utilization_rate"] = target_util

  target_marketing = round(_safe_float(solution.get("marketing_total_year1")), 2)
  constraint_profile = direct_inputs.get("constraint_profile") if isinstance(direct_inputs, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}
  reachable_market = max(0.0, _safe_float((marketing_children or {}).get("reachable_market")))
  capacity_units = max(0.0, _safe_float(direct_inputs.get("capacity_units")))
  target_units = max(0.0, capacity_units * (target_util or current_util))
  target_support_units = round(_safe_float(solution.get("marketing_support_units_year1")), 2)
  if reachable_market > 0 and target_units >= 0:
    marketing_model_patch["capture_rate_year1"] = round(target_units / max(reachable_market, 1e-9), 6)
  if target_support_units >= 0 and abs(target_support_units - marketing_support_units_baseline) >= 0.01:
    marketing_model_patch["expected_units_year1"] = target_support_units
  if target_units >= 0:
    marketing_model_patch["required_units_year1"] = round(target_units, 2)
    marketing_model_patch["demand_supports_required_units"] = True
  baseline_expected_customers = max(
    0.0,
    _safe_float((marketing_children or {}).get("baseline_expected_customers_or_clients_year1")),
  )
  baseline_expected_units = max(
    0.0,
    _safe_float((marketing_children or {}).get("baseline_expected_units_year1")),
  )
  if baseline_expected_customers > 0 and baseline_expected_units > 0 and target_support_units >= 0:
    scaled_expected_customers = baseline_expected_customers * (target_support_units / max(baseline_expected_units, 1e-9))
    if reachable_market > 0:
      scaled_expected_customers = min(reachable_market, scaled_expected_customers)
    marketing_model_patch["expected_customers_or_clients_year1"] = round(scaled_expected_customers, 2)

  target_other_opex = round(_safe_float(solution.get("other_operating_expense")), 2)
  if abs(target_other_opex - current_other_opex) >= 0.01:
    financials_patch["other_operating_expense"] = target_other_opex

  role_months = solution.get("role_months") if isinstance(solution, dict) else {}
  role_year1_payroll = solution.get("role_year1_payroll") if isinstance(solution, dict) else {}
  role_wage_meta = solution.get("role_wage_meta") if isinstance(solution, dict) else {}
  baseline_roles = {
    str(role.get("role_title") or "").strip(): max(0, min(12, _safe_int(role.get("base_months")) or 0))
    for role in (direct_inputs.get("roles") or [])
    if isinstance(role, dict)
  }
  baseline_role_wages = {
    str(role.get("role_title") or "").strip(): max(0.0, _safe_float(role.get("annual_wage")))
    for role in (direct_inputs.get("roles") or [])
    if isinstance(role, dict)
  }
  max_role_month = 0
  if isinstance(role_months, dict):
    for role_title, months in role_months.items():
      clean_title = str(role_title or "").strip()
      if not clean_title:
        continue
      target_months = max(0, min(12, _safe_int(months) or 0))
      baseline_months = baseline_roles.get(clean_title)
      meta = role_wage_meta.get(clean_title) if isinstance(role_wage_meta, dict) else {}
      target_year1_payroll = _safe_float(role_year1_payroll.get(clean_title)) if isinstance(role_year1_payroll, dict) else 0.0
      active_months = max(0, 12 - target_months)
      implied_wage = None
      if active_months > 0 and target_year1_payroll > 0:
        implied_wage = round((target_year1_payroll * 12.0) / active_months, 2)
      baseline_wage = baseline_role_wages.get(clean_title, 0.0)
      months_changed = baseline_months is not None and target_months != baseline_months
      wage_changed = implied_wage is not None and abs(implied_wage - baseline_wage) >= 0.01
      if baseline_months is None or (not months_changed and not wage_changed):
        continue
      update = {
        "role_title": clean_title,
        "months_until_hire": target_months,
      }
      if wage_changed:
        floor = _safe_float((meta or {}).get("wage_floor"))
        ceiling = _safe_float((meta or {}).get("wage_ceiling"))
        if floor > 0:
          implied_wage = max(floor, implied_wage)
        if ceiling > 0:
          implied_wage = min(ceiling, implied_wage)
        update["annual_wage"] = round(implied_wage, 2)
      people_role_updates.append(update)
      max_role_month = max(max_role_month, target_months)

  if financials_year1_patch:
    exact_patches["financials_year1_patch"] = financials_year1_patch
  if financials_patch:
    exact_patches["financials_patch"] = financials_patch
  if marketing_model_patch:
    exact_patches["marketing_model_patch"] = marketing_model_patch
  if people_role_updates:
    exact_patches["people_role_updates"] = people_role_updates
  if max_role_month > 0:
    milestone_updates = _attach_milestone_updates_for_delay(
      ops_json=ops_json,
      minimum_months=max_role_month,
    )
    if milestone_updates:
      exact_patches["milestone_updates"] = milestone_updates
  return exact_patches


def _family_cap_variants(candidate: Dict[str, Any]) -> List[Dict[str, float]]:
  raw = candidate.get("family_raw_components") if isinstance(candidate, dict) else {}
  raw = raw if isinstance(raw, dict) else {}
  ranked = [
    (str(name), max(0.0, _safe_float(value)))
    for name, value in raw.items()
    if max(0.0, _safe_float(value)) > 0.05
  ]
  ranked.sort(key=lambda item: item[1], reverse=True)
  variants: List[Dict[str, float]] = []
  for family_name, family_value in ranked[:3]:
    capped = max(0.0, family_value * 0.8)
    variants.append({family_name: capped})
  return variants


def build_consistency_solver_state(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  baseline_summary = build_consistency_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  if not _solver_required(baseline_summary):
    return None

  baseline_state = {
    "ops_json": _clone(ops_json or {}),
    "people_json": _clone(people_json or {}),
    "financials_json": _clone(financials_json or {}),
    "financials_year1_json": _clone(financials_year1_json or {}),
    "marketing_model_json": _clone(marketing_model_json or {}),
  }
  state_model = _build_solver_state_model(
    ops_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    baseline_summary=baseline_summary,
  )
  if not isinstance(state_model, dict):
    return None
  direct_inputs = _build_direct_solver_inputs(
    state_model=state_model,
  )
  if not isinstance(direct_inputs, dict):
    return None

  profiles = _solver_profiles(state_model=state_model)
  feasible_scenarios: List[Dict[str, Any]] = []
  fallback_scenarios: List[Dict[str, Any]] = []
  seen_feasible = set()
  seen_fallback = set()
  objective_policy = state_model.get("objective_policy") if isinstance(state_model, dict) else {}
  healthy_ratio = max(0.0, _safe_float((objective_policy or {}).get("healthy_ebitda_margin_ratio")))
  baseline_revenue = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
  healthy_ebitda_target = baseline_revenue * healthy_ratio if baseline_revenue > 0 and healthy_ratio > 0 else 0.0
  selected_target_label = "break_even"
  selected_target_amount = 0.0

  def _try_add_solution(
    *,
    profile: Dict[str, Any],
    target_ebitda_min: Optional[float],
    target_list: List[Dict[str, Any]],
    seen_signatures: set,
    family_caps: Optional[Dict[str, float]] = None,
  ) -> bool:
    solution = _solve_direct_profile(
      profile=profile,
      direct_inputs=direct_inputs,
      target_ebitda_min=target_ebitda_min,
      family_caps=family_caps,
    )
    if not isinstance(solution, dict):
      return False
    exact_patches = _exact_patches_from_solution(
      solution=solution,
      direct_inputs=direct_inputs,
      ops_json=ops_json,
    )
    signature = _scenario_signature(exact_patches)
    if not signature or signature in seen_signatures:
      return False
    candidate = _build_candidate_from_exact_patches(
      scenario_id=str(len(target_list) + 1),
      baseline_summary=baseline_summary,
      baseline_state=baseline_state,
      marketing_model_json=marketing_model_json,
      exact_patches=exact_patches,
    )
    if not candidate:
      return False
    candidate["solution_profile_id"] = str(solution.get("profile_id") or "")
    candidate["distortion_components"] = dict(solution.get("distortion_components") or {})
    candidate["distortion_total"] = _safe_float(solution.get("distortion_total"))
    candidate["family_raw_components"] = dict(solution.get("family_raw_components") or {})
    candidate["max_family_move"] = _safe_float(solution.get("max_family_move"))
    seen_signatures.add(signature)
    target_list.append(candidate)
    return True

  for profile in profiles:
    solved_for_profile = False
    for target_label, target_amount, target_list, seen_signatures in (
      ("healthy", healthy_ebitda_target if healthy_ebitda_target > 0 else None, feasible_scenarios, seen_feasible),
      ("break_even", 0.0, feasible_scenarios, seen_feasible),
      ("fallback", None, fallback_scenarios, seen_fallback),
    ):
      if target_label == "healthy" and healthy_ebitda_target <= 0:
        continue
      if _try_add_solution(
        profile=profile,
        target_ebitda_min=target_amount,
        target_list=target_list,
        seen_signatures=seen_signatures,
      ):
        if target_label != "fallback":
          feasible_scenarios[-1]["target_label"] = target_label
          feasible_scenarios[-1]["target_ebitda_min"] = target_amount
        else:
          fallback_scenarios[-1]["target_label"] = target_label
          fallback_scenarios[-1]["target_ebitda_min"] = None
        solved_for_profile = True
        break
    if solved_for_profile:
      continue

  if any(str(item.get("target_label") or "") == "healthy" for item in feasible_scenarios):
    feasible_scenarios = [
      item for item in feasible_scenarios
      if str(item.get("target_label") or "") == "healthy"
    ]
  break_even_found = bool(feasible_scenarios)
  scenarios = feasible_scenarios if feasible_scenarios else fallback_scenarios
  if feasible_scenarios:
    if any(str(item.get("target_label") or "") == "healthy" for item in feasible_scenarios):
      selected_target_label = "healthy"
      selected_target_amount = healthy_ebitda_target
    else:
      selected_target_label = "break_even"
      selected_target_amount = 0.0
  else:
    selected_target_label = "fallback"
    selected_target_amount = 0.0

  if not scenarios:
    return None

  profile_priority = {
    "balanced": 0,
    "growth_first": 1,
    "profit_first": 2,
    "lean_survival": 3,
  }
  scenarios.sort(
    key=lambda item: (
      profile_priority.get(str(item.get("solution_profile_id") or "").strip(), 99),
      0 if bool(item.get("break_even_ebitda")) else 1,
      _safe_float(item.get("ebitda_gap")),
      _safe_float(item.get("distortion_total")) or _safe_float(item.get("disruption_score")),
      -_safe_float(item.get("ebitda")),
    )
  )
  materially_distinct: List[Dict[str, Any]] = []
  used_profiles = set()
  for candidate in scenarios:
    profile_id = str(candidate.get("solution_profile_id") or "").strip()
    if profile_id in used_profiles:
      continue
    if any(not _materially_distinct_candidate(candidate, existing) for existing in materially_distinct):
      continue
    materially_distinct.append(candidate)
    used_profiles.add(profile_id)
    if len(materially_distinct) >= MAX_SCENARIOS:
      break
  if len(materially_distinct) < MAX_SCENARIOS:
    for candidate in scenarios:
      if any(candidate is existing for existing in materially_distinct):
        continue
      if any(not _materially_distinct_candidate(candidate, existing) for existing in materially_distinct):
        continue
      materially_distinct.append(candidate)
      if len(materially_distinct) >= MAX_SCENARIOS:
        break
  scenarios = materially_distinct[:MAX_SCENARIOS]

  normalized_selected: List[Dict[str, Any]] = []
  for index, candidate in enumerate(scenarios, start=1):
    normalized = dict(candidate)
    normalized["scenario_id"] = str(index)
    normalized_selected.append(normalized)

  return {
    "status": "awaiting_choice",
    "target_metric": "ebitda_break_even",
    "search_mode": "direct_pulp",
    "loss_threshold_ratio": LOSS_THRESHOLD_RATIO,
    "healthy_ebitda_margin_ratio": healthy_ratio,
    "selected_target_label": selected_target_label,
    "selected_target_ebitda_min": selected_target_amount,
    "baseline_summary": baseline_summary,
    "baseline_loss_pct": _loss_pct(baseline_summary),
    "baseline_table_markdown": build_consistency_financial_table(baseline_summary),
    "state_model": state_model,
    "structural_gap": not break_even_found,
    "scenarios": normalized_selected,
  }


def apply_consistency_solver_choice(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  solver_state: Dict[str, Any],
  selected_scenario_id: str,
  overrides: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  scenarios = solver_state.get("scenarios") if isinstance(solver_state, dict) else None
  if not isinstance(scenarios, list):
    return None
  selected = None
  for scenario in scenarios:
    if not isinstance(scenario, dict):
      continue
    if str(scenario.get("scenario_id") or "").strip() == str(selected_scenario_id or "").strip():
      selected = scenario
      break
  if not isinstance(selected, dict):
    return None

  exact_patches = _clone(selected.get("exact_patches") or {})
  overrides = overrides if isinstance(overrides, dict) else {}
  state_model = solver_state.get("state_model") if isinstance(solver_state, dict) else {}
  constraint_profile = (state_model or {}).get("constraint_profile") if isinstance(state_model, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}
  baseline_expected_units = max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1")))
  units_per_marketing_dollar = max(0.0, _safe_float(((constraint_profile or {}).get("demand_curve") or {}).get("units_per_marketing_dollar")))

  if overrides.get("price_change_percent") is not None:
    current_price = _safe_float(
      _top_level_driver_value(financials_year1_json or {}, "unit_price")
      or (ops_json or {}).get("unit_price")
    )
    pct = _safe_float(overrides.get("price_change_percent")) / 100.0
    if current_price > 0 and pct > 0:
      exact_patches.setdefault("financials_year1_patch", {})
      exact_patches["financials_year1_patch"]["unit_price"] = round(current_price * (1.0 + pct), 2)
  if overrides.get("unit_price_absolute") is not None:
    absolute_price = _safe_float(overrides.get("unit_price_absolute"))
    if absolute_price > 0:
      exact_patches.setdefault("financials_year1_patch", {})
      exact_patches["financials_year1_patch"]["unit_price"] = round(absolute_price, 2)

  if overrides.get("utilization_percent") is not None:
    util_ratio = _normalize_ratio(overrides.get("utilization_percent"))
    if util_ratio is not None:
      exact_patches.setdefault("financials_year1_patch", {})
      exact_patches["financials_year1_patch"]["utilization_rate"] = util_ratio

  if overrides.get("marketing_reduction_percent") is not None:
    current_marketing = _safe_float((financials_json or {}).get("marketing_total_year1"))
    pct = _safe_float(overrides.get("marketing_reduction_percent")) / 100.0
    if current_marketing > 0 and pct >= 0 and units_per_marketing_dollar > 0:
      target_marketing = round(current_marketing * (1.0 - pct), 2)
      target_units = round(target_marketing * units_per_marketing_dollar, 2)
      exact_patches.setdefault("marketing_model_patch", {})
      exact_patches["marketing_model_patch"]["expected_units_year1"] = target_units
  if overrides.get("marketing_total_year1_absolute") is not None:
    total = _safe_float(overrides.get("marketing_total_year1_absolute"))
    if total >= 0 and units_per_marketing_dollar > 0:
      target_units = round(total * units_per_marketing_dollar, 2)
      exact_patches.setdefault("marketing_model_patch", {})
      exact_patches["marketing_model_patch"]["expected_units_year1"] = target_units

  if overrides.get("other_opex_reduction_percent") is not None:
    current_other_opex = _safe_float((financials_json or {}).get("other_operating_expense"))
    pct = _safe_float(overrides.get("other_opex_reduction_percent")) / 100.0
    if current_other_opex > 0 and pct >= 0:
      exact_patches.setdefault("financials_patch", {})
      exact_patches["financials_patch"]["other_operating_expense"] = round(current_other_opex * (1.0 - pct), 2)
  if overrides.get("other_opex_absolute") is not None:
    total = _safe_float(overrides.get("other_opex_absolute"))
    if total >= 0:
      exact_patches.setdefault("financials_patch", {})
      exact_patches["financials_patch"]["other_operating_expense"] = round(total, 2)

  role_title = str(overrides.get("role_title") or "").strip().lower()
  months_until_hire = _safe_int(overrides.get("months_until_hire"))
  if role_title and months_until_hire is not None:
    role_updates = exact_patches.get("people_role_updates")
    if not isinstance(role_updates, list):
      role_updates = []
      exact_patches["people_role_updates"] = role_updates
    updated = False
    for item in role_updates:
      if not isinstance(item, dict):
        continue
      if str(item.get("role_title") or "").strip().lower() != role_title:
        continue
      item["months_until_hire"] = int(max(0, months_until_hire))
      updated = True
      break
    if not updated:
      role_updates.append(
        {"role_title": role_title, "months_until_hire": int(max(0, months_until_hire))}
      )
    milestone_updates = _attach_milestone_updates_for_delay(
      ops_json=ops_json,
      minimum_months=int(max(1, months_until_hire)),
    )
    if milestone_updates:
      exact_patches["milestone_updates"] = milestone_updates

  milestone_months = _safe_int(overrides.get("milestone_timing_months_max"))
  if milestone_months is not None and milestone_months > 0:
    milestone_updates = exact_patches.get("milestone_updates")
    if not isinstance(milestone_updates, list) or not milestone_updates:
      auto_updates = _attach_milestone_updates_for_delay(
        ops_json=ops_json,
        minimum_months=milestone_months,
      )
      milestone_updates = auto_updates if auto_updates else []
    for update in milestone_updates:
      if not isinstance(update, dict):
        continue
      update["timing_months_max"] = int(milestone_months)
      update["timing"] = _render_timing_text(int(milestone_months))
    if milestone_updates:
      exact_patches["milestone_updates"] = milestone_updates

  next_ops, next_people, next_financials, next_year1, next_marketing_model = _apply_exact_patches(
    ops_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    exact_patches=exact_patches,
  )
  violations = _scenario_violations(
    baseline_state={
      "ops_json": _clone(ops_json or {}),
      "people_json": _clone(people_json or {}),
      "financials_json": _clone(financials_json or {}),
      "financials_year1_json": _clone(financials_year1_json or {}),
      "marketing_model_json": _clone(marketing_model_json or {}),
    },
    next_ops=next_ops,
    next_financials=next_financials,
    next_year1=next_year1,
    exact_patches=exact_patches,
    marketing_model_json=next_marketing_model,
  )
  if violations:
    return None
  summary = build_consistency_financial_summary(
    financials_json=next_financials,
    financials_year1_json=next_year1,
  )
  return {
    "ops_json": next_ops,
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "marketing_model_json": next_marketing_model,
    "summary": summary,
    "exact_patches": exact_patches,
    "scenario": selected,
  }
