from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional, Tuple


def as_float_maybe(value: Any) -> Optional[float]:
  if value is None or isinstance(value, bool):
    return None
  try:
    return float(value)
  except Exception:
    return None


def _hash_inputs(inputs: Dict[str, Any]) -> str:
  try:
    raw = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  except Exception:
    raw = str(inputs)
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_model_card_for_write(card: Dict[str, Any], *, now_ms: int) -> Dict[str, Any]:
  """
  Normalize a model card into the {lobs:[...]} shape and ensure company_total exists.
  Backwards compatible with the older {drivers, derived} shape.
  """
  base = dict(card or {}) if isinstance(card, dict) else {}
  lobs = base.get("lobs")
  if not isinstance(lobs, list):
    drivers = base.get("drivers") if isinstance(base.get("drivers"), dict) else {}
    derived = base.get("derived") if isinstance(base.get("derived"), dict) else {}
    lobs = [
      {
        "lob_key": "company_total",
        "lob_name": None,
        "drivers": dict(drivers),
        "derived": dict(derived),
      }
    ]
  fixed_lobs: list[Dict[str, Any]] = []
  for lob in list(lobs or []):
    if not isinstance(lob, dict):
      continue
    lob_key = str(lob.get("lob_key") or "company_total").strip() or "company_total"
    fixed_lobs.append(
      {
        **lob,
        "lob_key": lob_key,
        "lob_name": str(lob.get("lob_name") or "").strip() or None,
        "drivers": lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {},
        "derived": lob.get("derived") if isinstance(lob.get("derived"), dict) else {},
      }
    )
  if not any(str(l.get("lob_key") or "").strip() == "company_total" for l in fixed_lobs):
    fixed_lobs = [{"lob_key": "company_total", "lob_name": None, "drivers": {}, "derived": {}}, *fixed_lobs]
  base_out = {
    **base,
    "version": int(base.get("version") or 1),
    "updated_at_ms": int(now_ms),
    "lobs": fixed_lobs,
  }
  base_out.pop("drivers", None)
  base_out.pop("derived", None)
  return base_out


def get_company_total_lob(card: Dict[str, Any]) -> Dict[str, Any]:
  lobs = card.get("lobs")
  if not isinstance(lobs, list):
    return {}
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    if str(lob.get("lob_key") or "").strip() == "company_total":
      return lob
  return {}

def get_lob(card: Dict[str, Any], *, lob_key: str) -> Dict[str, Any]:
  wanted = str(lob_key or "").strip() or "company_total"
  lobs = card.get("lobs")
  if not isinstance(lobs, list):
    return {}
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    if str(lob.get("lob_key") or "").strip() == wanted:
      return lob
  return {}


def set_lob_driver(
  card: Dict[str, Any],
  *,
  lob_key: str,
  key: str,
  value: Any,
  unit: Optional[str],
  time_basis: Optional[str],
  rationale: Optional[str],
  now_ms: int,
) -> Tuple[Dict[str, Any], bool]:
  """
  Set a single driver value on a specific LOB, preserving any existing metadata.
  Returns (next_card, changed).
  """
  normalized = normalize_model_card_for_write(card or {}, now_ms=now_ms)
  lob_key_norm = str(lob_key or "").strip() or "company_total"
  lob = get_lob(normalized, lob_key=lob_key_norm)
  if not lob:
    normalized["lobs"] = [
      *(normalized.get("lobs") if isinstance(normalized.get("lobs"), list) else []),
      {"lob_key": lob_key_norm, "lob_name": None, "drivers": {}, "derived": {}},
    ]
    lob = get_lob(normalized, lob_key=lob_key_norm)
  if not lob:
    return normalized, False

  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  drivers = dict(drivers)
  prev = drivers.get(key)
  prev_obj = dict(prev) if isinstance(prev, dict) else {}
  next_obj = {
    **prev_obj,
    "value": value,
    "unit": unit,
    "time_basis": time_basis,
    "rationale": rationale,
    "updated_at_ms": int(now_ms),
  }
  if prev_obj == next_obj:
    return normalized, False
  drivers[key] = next_obj
  lob["drivers"] = drivers
  normalized["updated_at_ms"] = int(now_ms)
  return normalized, True


def set_company_driver(
  card: Dict[str, Any],
  *,
  key: str,
  value: Any,
  unit: Optional[str],
  time_basis: Optional[str],
  rationale: Optional[str],
  now_ms: int,
) -> Tuple[Dict[str, Any], bool]:
  """
  Set a single driver value on company_total, preserving any existing metadata.
  Returns (next_card, changed).
  """
  normalized = normalize_model_card_for_write(card or {}, now_ms=now_ms)
  lob = get_company_total_lob(normalized)
  if not lob:
    return normalized, False

  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  drivers = dict(drivers)
  prev = drivers.get(key)
  prev_obj = dict(prev) if isinstance(prev, dict) else {}
  next_obj = {
    **prev_obj,
    "value": value,
    "unit": unit,
    "time_basis": time_basis,
    "rationale": rationale,
    "updated_at_ms": int(now_ms),
  }
  if prev_obj == next_obj:
    return normalized, False
  drivers[key] = next_obj
  lob["drivers"] = drivers
  normalized["updated_at_ms"] = int(now_ms)
  return normalized, True


def apply_company_driver_patch(
  *,
  model: str,
  field: str,
  value: Any,
  card: Dict[str, Any],
  ops_json: Dict[str, Any],
  now_ms: int,
  rationale: Optional[str] = None,
  unit_override: Optional[str] = None,
  time_basis_override: Optional[str] = None,
  lob_key: str = "company_total",
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
  """
  Apply a single chat-driven driver update to a model card, including any model-specific
  unit/time_basis conventions and any required cross-model sync (e.g., pricing -> ops).
  Returns (next_card, next_ops_json, changed).
  """
  model_norm = str(model or "").strip().lower()
  key = str(field or "").strip()
  if not model_norm or not key:
    return card or {}, ops_json or {}, False

  unit: Optional[str] = unit_override
  time_basis: Optional[str] = time_basis_override

  default_unit: Optional[str] = None
  default_time_basis: Optional[str] = None
  if model_norm == "marketing":
    if key == "monthly_marketing_budget":
      default_unit, default_time_basis = "USD", "month"
  elif model_norm == "pricing":
    if key == "unit_price":
      default_unit, default_time_basis = "USD", "per_unit"
  elif model_norm == "revenue":
    if key in ("units_per_week_capacity", "avg_units_per_week_year1"):
      default_unit = str((ops_json or {}).get("unit_name") or "").strip() or "units"
      default_time_basis = "week"
    elif key == "operating_weeks_per_year":
      default_unit, default_time_basis = "weeks", "year"
    elif key == "unit_price":
      default_unit, default_time_basis = "USD", "per_unit"
  elif model_norm == "cogs":
    if key.endswith("_cost_per_unit") or key == "cost_per_unit":
      default_unit, default_time_basis = "USD", "per_unit"
    elif key == "cogs_percent_of_revenue":
      default_unit, default_time_basis = "%", None
  elif model_norm == "gna":
    default_unit, default_time_basis = "USD", "month"

  if unit is None:
    unit = default_unit
  if time_basis is None:
    time_basis = default_time_basis

  next_card, changed = set_lob_driver(
    card or {},
    lob_key=str(lob_key or "").strip() or "company_total",
    key=key,
    value=value,
    unit=unit,
    time_basis=time_basis,
    rationale=str(rationale).strip() if rationale is not None and str(rationale).strip() else "Captured from chat.",
    now_ms=now_ms,
  )

  next_ops = dict(ops_json or {})
  if model_norm == "pricing" and changed and key == "unit_price" and str(lob_key or "").strip() in ("", "company_total"):
    try:
      next_card["unit_price"] = float(value)
    except Exception:
      next_card["unit_price"] = value
    try:
      next_ops["unit_price"] = float(value)
    except Exception:
      next_ops["unit_price"] = value

  return next_card, next_ops, changed


def set_company_derived(
  card: Dict[str, Any],
  *,
  key: str,
  value: Any,
  unit: Optional[str],
  time_basis: Optional[str],
  derivation: Optional[str],
  now_ms: int,
  inputs_hash: Optional[str] = None,
  computed_at_ms: Optional[int] = None,
) -> Dict[str, Any]:
  normalized = normalize_model_card_for_write(card or {}, now_ms=now_ms)
  lob = get_company_total_lob(normalized)
  if not lob:
    return normalized
  derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
  derived = dict(derived)
  entry = {
    "value": value,
    "unit": unit,
    "time_basis": time_basis,
    "derivation": derivation,
    "updated_at_ms": int(now_ms),
    "version": int(normalized.get("version") or 1),
  }
  if inputs_hash:
    entry["inputs_hash"] = inputs_hash
  if computed_at_ms is not None:
    entry["computed_at_ms"] = int(computed_at_ms)
  derived[key] = entry
  lob["derived"] = derived
  normalized["updated_at_ms"] = int(now_ms)
  return normalized


def ensure_pricing_from_ops(
  *, ops_json: Dict[str, Any], pricing_model_json: Dict[str, Any], rationale: Optional[str] = None
) -> Dict[str, Any]:
  unit_price = (ops_json or {}).get("unit_price")
  if unit_price in (None, ""):
    return pricing_model_json or {}
  try:
    unit_price_num = float(unit_price)
  except Exception:
    unit_price_num = unit_price

  # If already synced, avoid rewriting.
  try:
    existing_root_value = pricing_model_json.get("unit_price") if isinstance(pricing_model_json, dict) else None
    existing_driver_value: Any = None
    if isinstance(pricing_model_json, dict) and isinstance(pricing_model_json.get("lobs"), list):
      lob = get_company_total_lob(pricing_model_json)
      if isinstance(lob, dict):
        drivers_existing = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
        unit_driver_existing = drivers_existing.get("unit_price") if isinstance(drivers_existing, dict) else None
        if isinstance(unit_driver_existing, dict):
          existing_driver_value = unit_driver_existing.get("value")
    else:
      drivers_existing = pricing_model_json.get("drivers") if isinstance(pricing_model_json, dict) else None
      unit_driver_existing = drivers_existing.get("unit_price") if isinstance(drivers_existing, dict) else None
      if isinstance(unit_driver_existing, dict):
        existing_driver_value = unit_driver_existing.get("value")
    if existing_root_value == unit_price_num and existing_driver_value == unit_price_num:
      return pricing_model_json
  except Exception:
    pass

  now_ms = int(time.time() * 1000)
  normalized, _changed = set_company_driver(
    pricing_model_json or {},
    key="unit_price",
    value=unit_price_num,
    unit="USD",
    time_basis="per_unit",
    rationale=(
      str(rationale).strip()
      if rationale is not None and str(rationale).strip()
      else "Captured from the operational revenue model as the standard price per unit."
    ),
    now_ms=now_ms,
  )
  try:
    normalized["unit_price"] = unit_price_num
  except Exception:
    pass
  return normalized


def recompute_marketing_company_total(
  marketing_card: Dict[str, Any], *, now_ms: int
) -> Tuple[Dict[str, Any], Optional[float]]:
  normalized = normalize_model_card_for_write(marketing_card or {}, now_ms=now_ms)
  lob = get_company_total_lob(normalized)
  if not lob:
    return normalized, None
  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  monthly_val = None
  dv = drivers.get("monthly_marketing_budget")
  if isinstance(dv, dict):
    monthly_val = as_float_maybe(dv.get("value"))
  inputs_hash = _hash_inputs({"monthly_marketing_budget": monthly_val})
  year1 = (max(0.0, float(monthly_val)) * 12.0) if monthly_val is not None else None
  normalized = set_company_derived(
    normalized,
    key="year1_marketing_spend",
    value=year1,
    unit="USD",
    time_basis="year",
    derivation="monthly_marketing_budget x 12",
    now_ms=now_ms,
    inputs_hash=inputs_hash,
    computed_at_ms=now_ms,
  )
  return normalized, year1


def recompute_headcount_company_total(
  headcount_card: Dict[str, Any], *, now_ms: int
) -> Tuple[Dict[str, Any], Optional[float]]:
  normalized = normalize_model_card_for_write(headcount_card or {}, now_ms=now_ms)
  lob = get_company_total_lob(normalized)
  if not lob:
    return normalized, None
  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  roles = None
  roles_driver = drivers.get("roles")
  if isinstance(roles_driver, dict):
    roles = roles_driver.get("value")
  inputs_hash = _hash_inputs({"roles": roles})
  total = 0.0
  has_any = False
  if isinstance(roles, list):
    for r in roles:
      if not isinstance(r, dict):
        continue
      try:
        count = int(r.get("employee_count") or r.get("count") or 0)
      except Exception:
        count = 0
      if count <= 0:
        continue
      rate = as_float_maybe(r.get("hourly_rate_override"))
      if rate is None:
        rate = as_float_maybe(r.get("hourly_rate"))
      hpw = as_float_maybe(r.get("hours_per_week"))
      wpy = as_float_maybe(r.get("weeks_per_year"))
      hours_per_week = float(hpw) if hpw is not None else 40.0
      weeks_per_year = float(wpy) if wpy is not None else 52.0
      if rate is None:
        continue
      total += float(count) * float(rate) * float(hours_per_week) * float(weeks_per_year)
      has_any = True
  year1 = float(total) if has_any else None
  normalized = set_company_derived(
    normalized,
    key="year1_payroll",
    value=year1,
    unit="USD",
    time_basis="year",
    derivation="sum(employee_count x hourly_rate x hours_per_week x weeks_per_year)",
    now_ms=now_ms,
    inputs_hash=inputs_hash,
    computed_at_ms=now_ms,
  )
  return normalized, year1


def recompute_revenue_company_total(
  revenue_card: Dict[str, Any],
  *,
  ops_json: Dict[str, Any],
  now_ms: int,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[float]]:
  """
  Deterministically compute derived revenue values for company_total and keep the canonical
  ops_json (unit_price, units_per_week_capacity, starting_revenue) synced when possible.
  """
  normalized = normalize_model_card_for_write(revenue_card or {}, now_ms=now_ms)
  lob = get_company_total_lob(normalized)
  if not lob:
    return normalized, ops_json, None
  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  drivers = dict(drivers)

  def _driver_num(key: str) -> Optional[float]:
    dv = drivers.get(key)
    if isinstance(dv, dict):
      return as_float_maybe(dv.get("value"))
    return None

  capacity = _driver_num("units_per_week_capacity")
  if capacity is None:
    capacity = as_float_maybe((ops_json or {}).get("units_per_week_capacity"))
  unit_price = _driver_num("unit_price")
  if unit_price is None:
    unit_price = as_float_maybe((ops_json or {}).get("unit_price"))
  weeks = _driver_num("operating_weeks_per_year")
  if weeks is None:
    weeks = 52.0

  avg_units = _driver_num("avg_units_per_week_year1")
  util = _driver_num("utilization_rate")
  if util is not None and capacity is not None:
    avg_units = float(util) * float(capacity)
  elif avg_units is None:
    y1 = as_float_maybe((ops_json or {}).get("starting_revenue"))
    if y1 is not None and unit_price not in (None, 0) and weeks not in (None, 0):
      try:
        avg_units = float(y1) / float(unit_price) / float(weeks)
      except Exception:
        avg_units = None

  if avg_units is not None and capacity not in (None, 0):
    try:
      util_out = float(avg_units) / float(capacity)
    except Exception:
      util_out = None
  else:
    util_out = util

  if capacity is not None:
    drivers["units_per_week_capacity"] = {
      **(
        dict(drivers.get("units_per_week_capacity"))
        if isinstance(drivers.get("units_per_week_capacity"), dict)
        else {}
      ),
      "value": float(capacity),
      "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
      "time_basis": "week",
      "updated_at_ms": int(now_ms),
    }
  if unit_price is not None:
    drivers["unit_price"] = {
      **(dict(drivers.get("unit_price")) if isinstance(drivers.get("unit_price"), dict) else {}),
      "value": float(unit_price),
      "unit": "USD",
      "time_basis": "per_unit",
      "updated_at_ms": int(now_ms),
    }
  if weeks is not None:
    drivers["operating_weeks_per_year"] = {
      **(
        dict(drivers.get("operating_weeks_per_year"))
        if isinstance(drivers.get("operating_weeks_per_year"), dict)
        else {}
      ),
      "value": float(weeks),
      "unit": "weeks",
      "time_basis": "year",
      "updated_at_ms": int(now_ms),
    }
  if avg_units is not None:
    drivers["avg_units_per_week_year1"] = {
      **(
        dict(drivers.get("avg_units_per_week_year1"))
        if isinstance(drivers.get("avg_units_per_week_year1"), dict)
        else {}
      ),
      "value": float(avg_units),
      "unit": str((ops_json or {}).get("unit_name") or "").strip() or "units",
      "time_basis": "week",
      "updated_at_ms": int(now_ms),
    }
  if util_out is not None:
    drivers["utilization_rate"] = {
      **(dict(drivers.get("utilization_rate")) if isinstance(drivers.get("utilization_rate"), dict) else {}),
      "value": float(util_out),
      "unit": None,
      "time_basis": None,
      "updated_at_ms": int(now_ms),
    }

  lob["drivers"] = drivers

  y1_revenue: Optional[float] = None
  weekly_revenue: Optional[float] = None
  if avg_units is not None and unit_price is not None:
    weekly_revenue = float(avg_units) * float(unit_price)
    if weeks not in (None, 0):
      y1_revenue = weekly_revenue * float(weeks)

  normalized = set_company_derived(
    normalized,
    key="year1_revenue",
    value=y1_revenue,
    unit="USD",
    time_basis="year",
    derivation="avg_units_per_week_year1 x unit_price x operating_weeks_per_year",
    now_ms=now_ms,
    inputs_hash=_hash_inputs(
      {
        "avg_units_per_week_year1": avg_units,
        "unit_price": unit_price,
        "operating_weeks_per_year": weeks,
      }
    ),
    computed_at_ms=now_ms,
  )
  if weekly_revenue is not None:
    normalized = set_company_derived(
      normalized,
      key="weekly_revenue",
      value=weekly_revenue,
      unit="USD",
      time_basis="week",
      derivation="avg_units_per_week_year1 x unit_price",
      now_ms=now_ms,
      inputs_hash=_hash_inputs(
        {
          "avg_units_per_week_year1": avg_units,
          "unit_price": unit_price,
        }
      ),
      computed_at_ms=now_ms,
    )

  ops_out = dict(ops_json or {})
  if y1_revenue is not None:
    ops_out["starting_revenue"] = float(y1_revenue)
  if unit_price is not None:
    ops_out["unit_price"] = float(unit_price)
  if capacity is not None:
    ops_out["units_per_week_capacity"] = float(capacity)

  return normalized, ops_out, y1_revenue


def recompute_cogs_company_total(
  cogs_card: Dict[str, Any],
  *,
  revenue_card: Dict[str, Any],
  now_ms: int,
) -> Tuple[Dict[str, Any], Optional[float]]:
  """
  Compute year1_cogs.

  Supported driver bases (company_total):
  - cost_per_unit (USD per_unit): year1_cogs = avg_units_per_week_year1 * cost_per_unit * operating_weeks_per_year
  - cogs_percent_of_revenue (%): year1_cogs = year1_revenue * pct
  """
  normalized = normalize_model_card_for_write(cogs_card or {}, now_ms=now_ms)
  lob = get_company_total_lob(normalized)
  if not lob:
    return normalized, None

  rev_norm = normalize_model_card_for_write(revenue_card or {}, now_ms=now_ms)
  rev_lob = get_company_total_lob(rev_norm)
  rev_drivers = rev_lob.get("drivers") if isinstance(rev_lob.get("drivers"), dict) else {}
  rev_derived = rev_lob.get("derived") if isinstance(rev_lob.get("derived"), dict) else {}

  def _rev_driver_num(key: str) -> Optional[float]:
    dv = rev_drivers.get(key)
    if isinstance(dv, dict):
      return as_float_maybe(dv.get("value"))
    return None

  avg_units = _rev_driver_num("avg_units_per_week_year1")
  weeks = _rev_driver_num("operating_weeks_per_year") or 52.0
  year1_rev = None
  y1d = rev_derived.get("year1_revenue")
  if isinstance(y1d, dict):
    year1_rev = as_float_maybe(y1d.get("value"))

  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  cost_per_unit = None
  dv_cpu = drivers.get("cost_per_unit")
  if isinstance(dv_cpu, dict):
    cost_per_unit = as_float_maybe(dv_cpu.get("value"))

  if cost_per_unit is None:
    parts = (
      "materials_cost_per_unit",
      "direct_fulfillment_cost_per_unit",
      "other_variable_cost_per_unit",
    )
    total = 0.0
    has_any = False
    for k in parts:
      dv = drivers.get(k)
      v = as_float_maybe(dv.get("value")) if isinstance(dv, dict) else None
      if v is None:
        continue
      has_any = True
      total += max(0.0, float(v))
    if has_any:
      cost_per_unit = total
  pct = None
  dv_pct = drivers.get("cogs_percent_of_revenue")
  if isinstance(dv_pct, dict):
    pct = as_float_maybe(dv_pct.get("value"))

  year1_cogs: Optional[float] = None
  derivation: Optional[str] = None

  if cost_per_unit is not None and avg_units is not None and weeks not in (None, 0):
    year1_cogs = max(0.0, float(avg_units) * float(cost_per_unit) * float(weeks))
    derivation = "avg_units_per_week_year1 x cost_per_unit x operating_weeks_per_year"
  elif pct is not None and year1_rev is not None:
    pct_norm = float(pct)
    if pct_norm > 1.0:
      pct_norm = pct_norm / 100.0
    year1_cogs = max(0.0, float(year1_rev) * float(pct_norm))
    derivation = "year1_revenue x cogs_percent_of_revenue"

  normalized = set_company_derived(
    normalized,
    key="year1_cogs",
    value=year1_cogs,
    unit="USD",
    time_basis="year",
    derivation=derivation,
    now_ms=now_ms,
    inputs_hash=_hash_inputs(
      {
        "cost_per_unit": cost_per_unit,
        "cogs_percent_of_revenue": pct,
        "avg_units_per_week_year1": avg_units,
        "operating_weeks_per_year": weeks,
        "year1_revenue": year1_rev,
      }
    ),
    computed_at_ms=now_ms,
  )
  return normalized, year1_cogs


def recompute_gna_company_total(
  gna_card: Dict[str, Any], *, now_ms: int
) -> Tuple[Dict[str, Any], Optional[float]]:
  """
  Compute year1_gna_total as Σ(monthly drivers) x 12 for company_total.
  """
  normalized = normalize_model_card_for_write(gna_card or {}, now_ms=now_ms)
  lob = get_company_total_lob(normalized)
  if not lob:
    return normalized, None

  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}

  monthly_keys = (
    "monthly_rent_expense",
    "other_operating_expense",
    "other_monthly_debt_payments",
    "monthly_software_expense",
    "monthly_insurance_expense",
    "monthly_utilities_expense",
    "monthly_admin_expense",
  )
  monthly_sum = 0.0
  has_any = False
  used_parts: list[str] = []
  inputs_for_hash: Dict[str, Any] = {}
  for key in monthly_keys:
    dv = drivers.get(key)
    val = as_float_maybe(dv.get("value")) if isinstance(dv, dict) else None
    if val is None:
      continue
    has_any = True
    monthly_sum += max(0.0, float(val))
    used_parts.append(f"{key}")
    inputs_for_hash[key] = val

  # Include any additional explicitly-monthly drivers so the model is extensible without schema churn.
  try:
    for k, dv in drivers.items():
      if k in monthly_keys:
        continue
      if not isinstance(dv, dict):
        continue
      if str(dv.get("time_basis") or "").strip().lower() != "month":
        continue
      val = as_float_maybe(dv.get("value"))
      if val is None:
        continue
      has_any = True
      monthly_sum += max(0.0, float(val))
      used_parts.append(str(k))
      inputs_for_hash[str(k)] = val
  except Exception:
    pass

  year1 = (monthly_sum * 12.0) if has_any else None
  derivation = None
  if has_any:
    derivation = " + ".join(used_parts) + " (monthly) x 12"

  normalized = set_company_derived(
    normalized,
    key="year1_gna_total",
    value=year1,
    unit="USD",
    time_basis="year",
    derivation=derivation,
    now_ms=now_ms,
    inputs_hash=_hash_inputs(inputs_for_hash),
    computed_at_ms=now_ms,
  )
  return normalized, year1
