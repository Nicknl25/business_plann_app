from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_OPERATING_WEEKS_PER_YEAR = 52.0
DEFAULT_OPERATING_MONTHS_PER_YEAR = 12.0
DEFAULT_OPERATING_CONTRACT_PERIODS_PER_YEAR = 0.0


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  if isinstance(value, bool):
    return None
  if isinstance(value, (int, float)):
    return float(value)
  try:
    return float(str(value).strip().replace(",", ""))
  except Exception:
    return None


def _to_float(value: Any) -> Optional[float]:
  return _safe_float(value)


def _nonnegative(value: Optional[float]) -> Optional[float]:
  if value is None:
    return None
  if value < 0:
    return None
  return value


def _normalize_utilization(value: Any) -> Optional[float]:
  raw = _nonnegative(_to_float(value))
  if raw is None:
    return None
  if raw > 1.0:
    if raw > 100.0:
      return None
    return raw / 100.0
  return raw


def _normalize_cadence(value: Any) -> str:
  raw = str(value or "").strip().lower()
  if raw in ("weekly", "week", "per week", "wk", "w"):
    return "weekly"
  if raw in ("monthly", "month", "per month", "mo", "m"):
    return "monthly"
  if raw in ("contract", "retainer", "case", "engagement", "project"):
    return "contract"
  return "weekly"


def _cadence_label(cadence: str) -> str:
  cadence = _normalize_cadence(cadence)
  if cadence == "monthly":
    return "month"
  if cadence == "contract":
    return "contract"
  return "week"


def _cadence_periods_per_year(cadence: str) -> float:
  cadence = _normalize_cadence(cadence)
  if cadence == "monthly":
    return DEFAULT_OPERATING_MONTHS_PER_YEAR
  if cadence == "contract":
    return DEFAULT_OPERATING_CONTRACT_PERIODS_PER_YEAR
  return DEFAULT_OPERATING_WEEKS_PER_YEAR


def _cadence_driver_schema(cadence: str) -> Dict[str, str]:
  cadence = _normalize_cadence(cadence)
  if cadence == "contract":
    return {
      "cadence_type": "contract",
      "capacity_semantics": "max concurrent active units",
      "realized_units_semantics": "average active units during year 1",
      "periods_semantics": "annual turns per active slot",
      "annual_units_semantics": "annual completed units",
      "revenue_semantics": "avg active units x price x turns/year",
    }
  if cadence == "monthly":
    return {
      "cadence_type": "monthly",
      "capacity_semantics": "max units per month",
      "realized_units_semantics": "average units per month during year 1",
      "periods_semantics": "operating months per year",
      "annual_units_semantics": "annual delivered units",
      "revenue_semantics": "avg units/month x price x months/year",
    }
  return {
    "cadence_type": "weekly",
    "capacity_semantics": "max units per week",
    "realized_units_semantics": "average units per week during year 1",
    "periods_semantics": "operating weeks per year",
    "annual_units_semantics": "annual delivered units",
    "revenue_semantics": "avg units/week x price x weeks/year",
  }


def _cadence_authoritative_field_names(cadence: str) -> Dict[str, str]:
  cadence = _normalize_cadence(cadence)
  if cadence == "monthly":
    return {
      "avg_units_key": "avg_units_per_month_year1",
      "periods_key": "operating_months_per_year",
      "capacity_key": "units_per_month_capacity",
      "volume_semantics": "average monthly delivered units",
      "capacity_interpretation": "monthly throughput capacity",
    }
  if cadence == "contract":
    return {
      "avg_units_key": "avg_active_units_year1",
      "periods_key": "annual_turns_per_year",
      "capacity_key": "concurrent_capacity_units",
      "volume_semantics": "average active concurrent units",
      "capacity_interpretation": "concurrent active-load capacity",
    }
  return {
    "avg_units_key": "avg_units_per_week_year1",
    "periods_key": "operating_weeks_per_year",
    "capacity_key": "units_per_week_capacity",
    "volume_semantics": "average weekly delivered units",
    "capacity_interpretation": "weekly throughput capacity",
  }


def _pluralize(label: str, value: Any) -> str:
  count = _to_float(value)
  if count is None:
    return f"{label}s"
  if abs(count - 1.0) < 1e-6:
    return label
  return f"{label}s"


def _normalize_name(value: Any) -> str:
  return " ".join(str(value or "").strip().lower().split())


def _product_key(lob_name: str, product_name: str) -> str:
  return f"{_normalize_name(lob_name)}::{_normalize_name(product_name)}"


def _parse_lob_models(operating_model: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
  lob_models = operating_model.get("lob_models")
  if isinstance(lob_models, str):
    try:
      import json

      lob_models = json.loads(lob_models)
    except Exception:
      lob_models = None
  if isinstance(lob_models, list):
    return [lob for lob in lob_models if isinstance(lob, dict)]
  return None


def _build_default_lobs(operating_model: Dict[str, Any]) -> List[Dict[str, Any]]:
  business_type = str(operating_model.get("business_type") or "").strip()
  lob_name = business_type or "Primary line of business"
  unit_name = str(operating_model.get("unit_name") or "").strip() or "unit"
  product_name = unit_name or "Primary product"
  unit_cadence = _normalize_cadence(operating_model.get("unit_cadence"))
  units_per_period_capacity = operating_model.get("units_per_period_capacity")
  if units_per_period_capacity is None:
    units_per_period_capacity = operating_model.get("units_per_week_capacity")
  return [
    {
      "lob_name": lob_name,
      "products": [
        {
          "product_name": product_name,
          "unit_name": unit_name,
          "unit_description": str(operating_model.get("unit_description") or "").strip(),
          "unit_cadence": unit_cadence,
          "unit_price": operating_model.get("unit_price"),
          "units_per_week_capacity": operating_model.get("units_per_week_capacity"),
          "units_per_month_capacity": operating_model.get("units_per_month_capacity"),
          "concurrent_capacity_units": operating_model.get("concurrent_capacity_units"),
          "units_per_period_capacity": units_per_period_capacity,
          "avg_units_per_week_year1": operating_model.get("avg_units_per_week_year1"),
          "avg_units_per_month_year1": operating_model.get("avg_units_per_month_year1"),
          "avg_active_units_year1": operating_model.get("avg_active_units_year1"),
          "avg_units_per_period_year1": operating_model.get("avg_units_per_period_year1"),
          "operating_weeks_per_year": operating_model.get("operating_weeks_per_year"),
          "operating_months_per_year": operating_model.get("operating_months_per_year"),
          "annual_turns_per_year": operating_model.get("annual_turns_per_year"),
          "operating_periods_per_year": operating_model.get("operating_periods_per_year"),
          "utilization_rate": operating_model.get("utilization_rate"),
        }
      ],
    }
  ]


def _build_base_lobs(operating_model: Dict[str, Any]) -> List[Dict[str, Any]]:
  lob_models = _parse_lob_models(operating_model)
  if not lob_models:
    return _build_default_lobs(operating_model)

  base_lobs: List[Dict[str, Any]] = []
  for lob in lob_models:
    lob_name = str(lob.get("lob_name") or "").strip() or "Line of business"
    products_raw = lob.get("products")
    products_raw = products_raw if isinstance(products_raw, list) else []
    products: List[Dict[str, Any]] = []
    for product in products_raw:
      if not isinstance(product, dict):
        continue
      unit_name = str(product.get("unit_name") or "").strip() or str(operating_model.get("unit_name") or "").strip() or "unit"
      product_name = str(product.get("product_name") or "").strip() or unit_name or "Product"
      unit_cadence = _normalize_cadence(
        product.get("unit_cadence") or operating_model.get("unit_cadence")
      )
      units_per_period_capacity = product.get("units_per_period_capacity")
      if units_per_period_capacity is None:
        units_per_period_capacity = operating_model.get("units_per_period_capacity")
      if units_per_period_capacity is None:
        units_per_period_capacity = product.get("units_per_week_capacity")
      products.append(
        {
          "product_name": product_name,
          "unit_name": unit_name,
          "unit_description": str(product.get("unit_description") or "").strip()
          or str(operating_model.get("unit_description") or "").strip(),
          "unit_cadence": unit_cadence,
          "unit_price": product.get("unit_price"),
          "units_per_week_capacity": product.get("units_per_week_capacity"),
          "units_per_month_capacity": (
            product.get("units_per_month_capacity")
            if product.get("units_per_month_capacity") is not None
            else operating_model.get("units_per_month_capacity")
          ),
          "concurrent_capacity_units": (
            product.get("concurrent_capacity_units")
            if product.get("concurrent_capacity_units") is not None
            else operating_model.get("concurrent_capacity_units")
          ),
          "units_per_period_capacity": units_per_period_capacity,
          "avg_units_per_week_year1": (
            product.get("avg_units_per_week_year1")
            if product.get("avg_units_per_week_year1") is not None
            else operating_model.get("avg_units_per_week_year1")
          ),
          "avg_units_per_month_year1": (
            product.get("avg_units_per_month_year1")
            if product.get("avg_units_per_month_year1") is not None
            else operating_model.get("avg_units_per_month_year1")
          ),
          "avg_active_units_year1": (
            product.get("avg_active_units_year1")
            if product.get("avg_active_units_year1") is not None
            else operating_model.get("avg_active_units_year1")
          ),
          "avg_units_per_period_year1": (
            product.get("avg_units_per_period_year1")
            if product.get("avg_units_per_period_year1") is not None
            else operating_model.get("avg_units_per_period_year1")
          ),
          "operating_weeks_per_year": (
            product.get("operating_weeks_per_year")
            if product.get("operating_weeks_per_year") is not None
            else operating_model.get("operating_weeks_per_year")
          ),
          "operating_months_per_year": (
            product.get("operating_months_per_year")
            if product.get("operating_months_per_year") is not None
            else operating_model.get("operating_months_per_year")
          ),
          "annual_turns_per_year": (
            product.get("annual_turns_per_year")
            if product.get("annual_turns_per_year") is not None
            else operating_model.get("annual_turns_per_year")
          ),
          "operating_periods_per_year": product.get("operating_periods_per_year")
          if product.get("operating_periods_per_year") is not None
          else operating_model.get("operating_periods_per_year"),
          "utilization_rate": product.get("utilization_rate")
          if product.get("utilization_rate") is not None
          else operating_model.get("utilization_rate"),
        }
      )
    if not products:
      products = _build_default_lobs(operating_model)[0]["products"]
    base_lobs.append({"lob_name": lob_name, "products": products})
  return base_lobs


def _build_existing_product_map(existing_year1: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
  by_key: Dict[str, Dict[str, Any]] = {}
  by_name: Dict[str, Dict[str, Any]] = {}
  lobs = existing_year1.get("lobs")
  if not isinstance(lobs, list):
    return by_key, by_name

  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip()
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip()
      if not product_name:
        continue
      key = _product_key(lob_name, product_name)
      by_key[key] = product
      by_name[_normalize_name(product_name)] = product
  return by_key, by_name


def _product_has_positive_driver(product: Dict[str, Any]) -> bool:
  for key in ("unit_price", "units_per_period_capacity", "units_per_week_capacity"):
    value = _nonnegative(_to_float(product.get(key)))
    if value is not None and value > 0:
      return True
  return False


def _existing_drivers_are_zeroed(
  existing_year1: Dict[str, Any],
  base_lobs: List[Dict[str, Any]],
) -> bool:
  existing_lobs = existing_year1.get("lobs")
  if not isinstance(existing_lobs, list):
    # Handle legacy/global-only payloads with zeroed drivers (no lobs).
    global_positive = False
    for key in (
      "unit_price",
      "units_per_period_capacity",
      "units_per_week_capacity",
      "avg_units_per_period_year1",
      "avg_units_per_week_year1",
    ):
      value = _nonnegative(_to_float(existing_year1.get(key)))
      if value is not None and value > 0:
        global_positive = True
        break
    if global_positive:
      return False
    for lob in base_lobs:
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product in products:
        if not isinstance(product, dict):
          continue
        if _product_has_positive_driver(product):
          return True
    return False
  saw_existing_product = False
  for lob in existing_lobs:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      saw_existing_product = True
      if _product_has_positive_driver(product):
        return False
  if not saw_existing_product:
    return False
  for lob in base_lobs:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      if _product_has_positive_driver(product):
        return True
  return False


def _apply_override_value(raw: Any, fallback: Any) -> Any:
  return raw if raw is not None else fallback


def _derive_realized_volume_and_utilization(
  *,
  unit_cadence: str,
  units_per_period_capacity: float,
  utilization_rate: Optional[float],
  avg_units_per_period_year1: Optional[float],
) -> Tuple[float, Optional[float]]:
  capacity = _nonnegative(_to_float(units_per_period_capacity)) or 0.0
  utilization = _normalize_utilization(utilization_rate)
  avg_units = _nonnegative(_to_float(avg_units_per_period_year1))

  if avg_units is not None:
    if capacity > 0:
      utilization = min(max(avg_units / capacity, 0.0), 1.0)
    return float(avg_units), utilization

  if utilization is not None and capacity > 0:
    return float(utilization * capacity), float(utilization)

  return 0.0, (0.0 if capacity > 0 else None)


def _apply_canonical_period_fields(
  *,
  out: Dict[str, Any],
  unit_cadence: str,
  avg_units_per_period_year1: float,
  operating_periods_per_year: float,
  units_per_period_capacity: float,
  unit_price: float,
  utilization_rate: Optional[float],
) -> Dict[str, Any]:
  cadence = _normalize_cadence(unit_cadence)
  annual_units_year1 = float(avg_units_per_period_year1 * operating_periods_per_year)
  revenue_total_year1 = float(annual_units_year1 * unit_price)
  authoritative = _cadence_authoritative_field_names(cadence)

  out["unit_cadence"] = cadence
  out["unit_price"] = float(unit_price)
  out["units_per_period_capacity"] = float(units_per_period_capacity)
  out["avg_units_per_period_year1"] = float(avg_units_per_period_year1)
  out["operating_periods_per_year"] = float(operating_periods_per_year)
  out["annual_units_year1"] = annual_units_year1
  out["revenue_total_year1"] = revenue_total_year1
  out["driver_schema"] = _cadence_driver_schema(cadence)
  out["cadence_metadata"] = {
    "cadence_type": cadence,
    "authoritative_avg_units_field": authoritative["avg_units_key"],
    "authoritative_periods_field": authoritative["periods_key"],
    "authoritative_capacity_field": authoritative["capacity_key"],
    "capacity_interpretation": authoritative["capacity_interpretation"],
    "volume_semantics": authoritative["volume_semantics"],
    "operating_periods_per_year": float(operating_periods_per_year),
  }

  if utilization_rate is not None:
    out["utilization_rate"] = float(utilization_rate)
  elif "utilization_rate" in out:
    out.pop("utilization_rate", None)

  # Preserve cadence-specific aliases for downstream compatibility while keeping
  # the semantics explicit.
  out.pop("avg_units_per_week_year1", None)
  out.pop("operating_weeks_per_year", None)
  out.pop("avg_units_per_month_year1", None)
  out.pop("operating_months_per_year", None)
  out.pop("units_per_month_capacity", None)
  out.pop("avg_active_units_year1", None)
  out.pop("annual_turns_per_year", None)
  out.pop("annual_completed_units_year1", None)
  out.pop("concurrent_capacity_units", None)

  if cadence == "weekly":
    out["avg_units_per_week_year1"] = float(avg_units_per_period_year1)
    out["operating_weeks_per_year"] = float(operating_periods_per_year)
    out["units_per_week_capacity"] = float(units_per_period_capacity)
  elif cadence == "monthly":
    out["avg_units_per_month_year1"] = float(avg_units_per_period_year1)
    out["operating_months_per_year"] = float(operating_periods_per_year)
    out["units_per_month_capacity"] = float(units_per_period_capacity)
  elif cadence == "contract":
    out["avg_active_units_year1"] = float(avg_units_per_period_year1)
    out["annual_turns_per_year"] = float(operating_periods_per_year)
    out["annual_completed_units_year1"] = annual_units_year1
    out["concurrent_capacity_units"] = float(units_per_period_capacity)

  return out


def _apply_product_drivers(
  *,
  base_product: Dict[str, Any],
  override: Dict[str, Any],
  global_override: Dict[str, Any],
) -> Dict[str, Any]:
  unit_cadence = _apply_override_value(override.get("unit_cadence"), base_product.get("unit_cadence"))
  unit_cadence = _apply_override_value(global_override.get("unit_cadence"), unit_cadence)
  unit_cadence = _normalize_cadence(unit_cadence)

  unit_price = _apply_override_value(override.get("unit_price"), base_product.get("unit_price"))
  unit_price = _apply_override_value(global_override.get("unit_price"), unit_price)
  unit_price = _nonnegative(_to_float(unit_price)) or 0.0

  utilization_rate = _apply_override_value(
    override.get("utilization_rate"), base_product.get("utilization_rate")
  )
  utilization_rate = _apply_override_value(global_override.get("utilization_rate"), utilization_rate)
  utilization_rate = _normalize_utilization(utilization_rate)

  if unit_cadence == "weekly":
    units_per_period_capacity = _apply_override_value(
      override.get("units_per_week_capacity"), base_product.get("units_per_week_capacity")
    )
    units_per_period_capacity = _apply_override_value(
      global_override.get("units_per_week_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      base_product.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      override.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      global_override.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _nonnegative(_to_float(units_per_period_capacity)) or 0.0

    operating_periods_per_year = _apply_override_value(
      override.get("operating_weeks_per_year"), base_product.get("operating_weeks_per_year")
    )
    operating_periods_per_year = _apply_override_value(
      global_override.get("operating_weeks_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      base_product.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      override.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      global_override.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _nonnegative(_to_float(operating_periods_per_year))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _cadence_periods_per_year(unit_cadence)

    avg_units_per_period_year1 = _apply_override_value(
      override.get("avg_units_per_week_year1"), base_product.get("avg_units_per_week_year1")
    )
    avg_units_per_period_year1 = _apply_override_value(
      global_override.get("avg_units_per_week_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      base_product.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      override.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      global_override.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _nonnegative(_to_float(avg_units_per_period_year1))
  elif unit_cadence == "monthly":
    units_per_period_capacity = _apply_override_value(
      override.get("units_per_month_capacity"), base_product.get("units_per_month_capacity")
    )
    units_per_period_capacity = _apply_override_value(
      global_override.get("units_per_month_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      base_product.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      override.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      global_override.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _nonnegative(_to_float(units_per_period_capacity)) or 0.0

    operating_periods_per_year = _apply_override_value(
      override.get("operating_months_per_year"), base_product.get("operating_months_per_year")
    )
    operating_periods_per_year = _apply_override_value(
      global_override.get("operating_months_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      base_product.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      override.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      global_override.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _nonnegative(_to_float(operating_periods_per_year))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _cadence_periods_per_year(unit_cadence)

    avg_units_per_period_year1 = _apply_override_value(
      override.get("avg_units_per_month_year1"), base_product.get("avg_units_per_month_year1")
    )
    avg_units_per_period_year1 = _apply_override_value(
      global_override.get("avg_units_per_month_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      base_product.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      override.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      global_override.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _nonnegative(_to_float(avg_units_per_period_year1))
  else:
    units_per_period_capacity = _apply_override_value(
      override.get("concurrent_capacity_units"), base_product.get("concurrent_capacity_units")
    )
    units_per_period_capacity = _apply_override_value(
      global_override.get("concurrent_capacity_units"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      base_product.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      override.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _apply_override_value(
      global_override.get("units_per_period_capacity"), units_per_period_capacity
    )
    units_per_period_capacity = _nonnegative(_to_float(units_per_period_capacity)) or 0.0

    operating_periods_per_year = _apply_override_value(
      override.get("annual_turns_per_year"), base_product.get("annual_turns_per_year")
    )
    operating_periods_per_year = _apply_override_value(
      global_override.get("annual_turns_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      base_product.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      override.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _apply_override_value(
      global_override.get("operating_periods_per_year"), operating_periods_per_year
    )
    operating_periods_per_year = _nonnegative(_to_float(operating_periods_per_year))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _cadence_periods_per_year(unit_cadence)

    avg_units_per_period_year1 = _apply_override_value(
      override.get("avg_active_units_year1"), base_product.get("avg_active_units_year1")
    )
    avg_units_per_period_year1 = _apply_override_value(
      global_override.get("avg_active_units_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      base_product.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      override.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _apply_override_value(
      global_override.get("avg_units_per_period_year1"), avg_units_per_period_year1
    )
    avg_units_per_period_year1 = _nonnegative(_to_float(avg_units_per_period_year1))

  avg_units_per_period_year1, utilization_rate = _derive_realized_volume_and_utilization(
    unit_cadence=unit_cadence,
    units_per_period_capacity=units_per_period_capacity,
    utilization_rate=utilization_rate,
    avg_units_per_period_year1=avg_units_per_period_year1,
  )

  out = dict(base_product)
  return _apply_canonical_period_fields(
    out=out,
    unit_cadence=unit_cadence,
    avg_units_per_period_year1=avg_units_per_period_year1,
    operating_periods_per_year=operating_periods_per_year,
    units_per_period_capacity=units_per_period_capacity,
    unit_price=unit_price,
    utilization_rate=utilization_rate,
  )


def assemble_financials_year1(
  shared_context: Dict[str, Any],
  existing_year1: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  existing = existing_year1 if isinstance(existing_year1, dict) else {}
  operating_model = shared_context.get("operating_model")
  if not isinstance(operating_model, dict):
    operating_model = {}

  base_lobs = _build_base_lobs(operating_model)
  if _existing_drivers_are_zeroed(existing, base_lobs):
    existing = {}
  by_key, by_name = _build_existing_product_map(existing)

  lobs_out: List[Dict[str, Any]] = []
  company_total = 0.0

  for lob in base_lobs:
    lob_name = str(lob.get("lob_name") or "").strip() or "Line of business"
    products = lob.get("products")
    products = products if isinstance(products, list) else []
    products_out: List[Dict[str, Any]] = []
    lob_total = 0.0

    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip() or "Product"
      key = _product_key(lob_name, product_name)
      override = by_key.get(key) or by_name.get(_normalize_name(product_name)) or {}
      product_out = _apply_product_drivers(
        base_product=product,
        override=override if isinstance(override, dict) else {},
        global_override={},
      )
      products_out.append(product_out)
      lob_total += float(product_out.get("revenue_total_year1") or 0.0)

    lobs_out.append(
      {
        "lob_name": lob_name,
        "products": products_out,
        "revenue_total_year1": float(lob_total),
      }
    )
    company_total += lob_total

  return {
    "lobs": lobs_out,
    "company_revenue_total_year1": float(company_total),
  }


def _apply_patch_to_product(product: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
  next_product = dict(product or {})

  if "unit_cadence" in patch:
    next_product["unit_cadence"] = _normalize_cadence(patch.get("unit_cadence"))
  if "unit_price" in patch:
    next_product["unit_price"] = _nonnegative(_to_float(patch.get("unit_price"))) or 0.0
  if "units_per_week_capacity" in patch:
    next_product["units_per_week_capacity"] = _nonnegative(
      _to_float(patch.get("units_per_week_capacity"))
    ) or 0.0
  if "units_per_month_capacity" in patch:
    next_product["units_per_month_capacity"] = _nonnegative(
      _to_float(patch.get("units_per_month_capacity"))
    ) or 0.0
  if "concurrent_capacity_units" in patch:
    next_product["concurrent_capacity_units"] = _nonnegative(
      _to_float(patch.get("concurrent_capacity_units"))
    ) or 0.0
  if "units_per_period_capacity" in patch:
    next_product["units_per_period_capacity"] = _nonnegative(
      _to_float(patch.get("units_per_period_capacity"))
    ) or 0.0
  if "operating_weeks_per_year" in patch:
    next_product["operating_weeks_per_year"] = _nonnegative(
      _to_float(patch.get("operating_weeks_per_year"))
    ) or 0.0
  if "operating_months_per_year" in patch:
    next_product["operating_months_per_year"] = _nonnegative(
      _to_float(patch.get("operating_months_per_year"))
    ) or 0.0
  if "annual_turns_per_year" in patch:
    next_product["annual_turns_per_year"] = _nonnegative(
      _to_float(patch.get("annual_turns_per_year"))
    ) or 0.0
  if "operating_periods_per_year" in patch:
    next_product["operating_periods_per_year"] = _nonnegative(
      _to_float(patch.get("operating_periods_per_year"))
    ) or 0.0
  if "avg_units_per_week_year1" in patch:
    next_product["avg_units_per_week_year1"] = _nonnegative(
      _to_float(patch.get("avg_units_per_week_year1"))
    ) or 0.0
  if "avg_units_per_month_year1" in patch:
    next_product["avg_units_per_month_year1"] = _nonnegative(
      _to_float(patch.get("avg_units_per_month_year1"))
    ) or 0.0
  if "avg_active_units_year1" in patch:
    next_product["avg_active_units_year1"] = _nonnegative(
      _to_float(patch.get("avg_active_units_year1"))
    ) or 0.0
  if "avg_units_per_period_year1" in patch:
    next_product["avg_units_per_period_year1"] = _nonnegative(
      _to_float(patch.get("avg_units_per_period_year1"))
    ) or 0.0
  if "utilization_rate" in patch:
    util = _normalize_utilization(patch.get("utilization_rate"))
    if util is not None:
      next_product["utilization_rate"] = util

  unit_cadence = _normalize_cadence(next_product.get("unit_cadence"))
  unit_price = _nonnegative(_to_float(next_product.get("unit_price"))) or 0.0
  if unit_cadence == "weekly":
    units_per_period_capacity = _nonnegative(
      _to_float(next_product.get("units_per_week_capacity"))
    )
    if units_per_period_capacity is None:
      units_per_period_capacity = _nonnegative(_to_float(next_product.get("units_per_period_capacity")))
    units_per_period_capacity = units_per_period_capacity or 0.0
    operating_periods_per_year = _nonnegative(_to_float(next_product.get("operating_weeks_per_year")))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _nonnegative(_to_float(next_product.get("operating_periods_per_year")))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _cadence_periods_per_year(unit_cadence)
    avg_units_per_period_year1 = _nonnegative(_to_float(next_product.get("avg_units_per_week_year1")))
    if avg_units_per_period_year1 is None:
      avg_units_per_period_year1 = _nonnegative(_to_float(next_product.get("avg_units_per_period_year1")))
  elif unit_cadence == "monthly":
    units_per_period_capacity = _nonnegative(
      _to_float(next_product.get("units_per_month_capacity"))
    )
    if units_per_period_capacity is None:
      units_per_period_capacity = _nonnegative(_to_float(next_product.get("units_per_period_capacity")))
    units_per_period_capacity = units_per_period_capacity or 0.0
    operating_periods_per_year = _nonnegative(_to_float(next_product.get("operating_months_per_year")))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _nonnegative(_to_float(next_product.get("operating_periods_per_year")))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _cadence_periods_per_year(unit_cadence)
    avg_units_per_period_year1 = _nonnegative(_to_float(next_product.get("avg_units_per_month_year1")))
    if avg_units_per_period_year1 is None:
      avg_units_per_period_year1 = _nonnegative(_to_float(next_product.get("avg_units_per_period_year1")))
  else:
    units_per_period_capacity = _nonnegative(
      _to_float(next_product.get("concurrent_capacity_units"))
    )
    if units_per_period_capacity is None:
      units_per_period_capacity = _nonnegative(_to_float(next_product.get("units_per_period_capacity")))
    units_per_period_capacity = units_per_period_capacity or 0.0
    operating_periods_per_year = _nonnegative(_to_float(next_product.get("annual_turns_per_year")))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _nonnegative(_to_float(next_product.get("operating_periods_per_year")))
    if operating_periods_per_year is None or operating_periods_per_year <= 0:
      operating_periods_per_year = _cadence_periods_per_year(unit_cadence)
    avg_units_per_period_year1 = _nonnegative(_to_float(next_product.get("avg_active_units_year1")))
    if avg_units_per_period_year1 is None:
      avg_units_per_period_year1 = _nonnegative(_to_float(next_product.get("avg_units_per_period_year1")))

  avg_units_per_period_year1, utilization_rate = _derive_realized_volume_and_utilization(
    unit_cadence=unit_cadence,
    units_per_period_capacity=units_per_period_capacity,
    utilization_rate=next_product.get("utilization_rate"),
    avg_units_per_period_year1=avg_units_per_period_year1,
  )

  return _apply_canonical_period_fields(
    out=next_product,
    unit_cadence=unit_cadence,
    avg_units_per_period_year1=avg_units_per_period_year1,
    operating_periods_per_year=operating_periods_per_year,
    units_per_period_capacity=units_per_period_capacity,
    unit_price=unit_price,
    utilization_rate=utilization_rate,
  )


def apply_revenue_driver_patch(
  financials_year1_json: Dict[str, Any],
  patch: Dict[str, Any],
) -> Dict[str, Any]:
  next_year1 = dict(financials_year1_json or {})
  if not isinstance(patch, dict):
    patch = {}

  lobs = next_year1.get("lobs")
  if not isinstance(lobs, list):
    return next_year1

  product_overrides = patch.get("product_overrides")
  product_overrides = product_overrides if isinstance(product_overrides, dict) else {}
  overrides_by_key = {
    _normalize_name(name): value
    for name, value in product_overrides.items()
    if isinstance(value, dict)
  }

  # In child-first mode, product overrides are the source of truth and parent/global
  # revenue-driver patches must not leak back down into children.
  global_patch: Dict[str, Any] = {}
  if not overrides_by_key:
    global_patch = {
      key: patch[key]
      for key in (
        "unit_cadence",
        "unit_price",
        "units_per_week_capacity",
        "units_per_month_capacity",
        "concurrent_capacity_units",
        "units_per_period_capacity",
        "avg_units_per_week_year1",
        "avg_units_per_month_year1",
        "avg_active_units_year1",
        "avg_units_per_period_year1",
        "operating_weeks_per_year",
        "operating_months_per_year",
        "annual_turns_per_year",
        "operating_periods_per_year",
        "utilization_rate",
      )
      if key in patch
    }

  lobs_out: List[Dict[str, Any]] = []
  company_total = 0.0

  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip() or "Line of business"
    products = lob.get("products")
    products = products if isinstance(products, list) else []
    products_out: List[Dict[str, Any]] = []
    lob_total = 0.0

    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip() or "Product"
      override = (
        overrides_by_key.get(_product_key(lob_name, product_name))
        or overrides_by_key.get(_normalize_name(product_name))
      )
      merged_patch = dict(global_patch)
      if isinstance(override, dict):
        merged_patch.update(override)
      updated = _apply_patch_to_product(product, merged_patch)
      products_out.append(updated)
      lob_total += float(updated.get("revenue_total_year1") or 0.0)

    lobs_out.append(
      {
        "lob_name": lob_name,
        "products": products_out,
        "revenue_total_year1": float(lob_total),
      }
    )
    company_total += lob_total

  next_year1["lobs"] = lobs_out
  next_year1["company_revenue_total_year1"] = float(company_total)
  return next_year1


def _format_number(value: Any) -> str:
  raw = _to_float(value)
  if raw is None:
    return "0"
  if abs(raw - round(raw)) < 1e-6:
    return str(int(round(raw)))
  text = f"{raw:.2f}"
  text = text.rstrip("0").rstrip(".")
  return text or "0"


def _format_currency(value: Any) -> str:
  raw = _to_float(value)
  if raw is None:
    return "$0"
  if abs(raw - round(raw)) < 1e-6:
    return f"${int(round(raw)):,}"
  return f"${raw:,.2f}"


def _format_percent(value: Optional[float]) -> str:
  if value is None:
    return "0%"
  pct = value * 100.0
  if abs(pct - round(pct)) < 1e-6:
    return f"{int(round(pct))}%"
  return f"{pct:.1f}%"


def _parse_milestones(raw: Any) -> List[Dict[str, Any]]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return [m for m in raw if isinstance(m, dict)]
  if isinstance(raw, str):
    try:
      parsed = json.loads(raw)
    except Exception:
      return []
    if isinstance(parsed, list):
      return [m for m in parsed if isinstance(m, dict)]
  return []


def _summarize_milestones(milestones: List[Dict[str, Any]], *, max_items: int = 2) -> str:
  items: List[str] = []
  for milestone in milestones:
    desc = str(milestone.get("description") or "").strip()
    timing = str(milestone.get("timing") or "").strip()
    if desc and timing:
      items.append(f"{desc} ({timing})")
    elif desc:
      items.append(desc)
    elif timing:
      items.append(timing)
  if not items:
    return ""
  if len(items) > max_items:
    remaining = len(items) - max_items
    return ", ".join(items[:max_items]) + f", +{remaining} more"
  return ", ".join(items)


def _build_utilization_summary(financials_year1_json: Dict[str, Any], *, max_items: int = 4) -> List[str]:
  lobs = financials_year1_json.get("lobs")
  if not isinstance(lobs, list):
    return []
  lines: List[str] = []
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    products = products if isinstance(products, list) else []
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip() or "Product"
      unit_label = str(product.get("unit_name") or "").strip() or "units"
      cadence = _normalize_cadence(product.get("unit_cadence"))
      period_label = _cadence_label(cadence)
      if cadence == "contract":
        avg_units_val = _to_float(product.get("avg_active_units_year1"))
        if avg_units_val is None:
          avg_units_val = _to_float(product.get("avg_units_per_period_year1"))
        capacity_val = _to_float(product.get("concurrent_capacity_units"))
        if capacity_val is None:
          capacity_val = _to_float(product.get("units_per_period_capacity"))
      elif cadence == "monthly":
        avg_units_val = _to_float(product.get("avg_units_per_month_year1"))
        if avg_units_val is None:
          avg_units_val = _to_float(product.get("avg_units_per_period_year1"))
        capacity_val = _to_float(product.get("units_per_month_capacity"))
        if capacity_val is None:
          capacity_val = _to_float(product.get("units_per_period_capacity"))
      else:
        avg_units_val = _to_float(product.get("avg_units_per_week_year1"))
        if avg_units_val is None:
          avg_units_val = _to_float(product.get("avg_units_per_period_year1"))
        capacity_val = _to_float(product.get("units_per_week_capacity"))
        if capacity_val is None:
          capacity_val = _to_float(product.get("units_per_period_capacity"))
      utilization_rate = _normalize_utilization(product.get("utilization_rate"))

      if avg_units_val is None and capacity_val is None and utilization_rate is None:
        continue

      if cadence == "contract" and avg_units_val is not None and capacity_val is not None:
        avg_units = _format_number(avg_units_val)
        capacity = _format_number(capacity_val)
        turns = _format_number(product.get("annual_turns_per_year") or product.get("operating_periods_per_year"))
        line = (
          f"{product_name}: avg active {avg_units} {unit_label} on "
          f"{capacity} active-{unit_label} capacity at ~{turns} turns/year"
        )
      elif avg_units_val is not None and capacity_val is not None:
        avg_units = _format_number(avg_units_val)
        capacity = _format_number(capacity_val)
        line = (
          f"{product_name}: avg {avg_units} {unit_label}/{period_label} on "
          f"{capacity} {unit_label}/{period_label} capacity"
        )
      elif utilization_rate is not None:
        line = f"{product_name}: {_format_percent(utilization_rate)} utilization"
      elif avg_units_val is not None:
        avg_units = _format_number(avg_units_val)
        line = f"{product_name}: avg {avg_units} {unit_label}/{period_label}"
      else:
        capacity = _format_number(capacity_val)
        line = f"{product_name}: capacity {capacity} {unit_label}/{period_label}"

      lines.append(line)

  if len(lines) > max_items:
    remaining = len(lines) - max_items
    lines = lines[:max_items]
    lines[-1] = f"{lines[-1]}; +{remaining} more products"
  return lines


def build_revenue_constraints_snippet(
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  *,
  business_start_date: Optional[str] = None,
) -> str:
  operating_model = shared_context.get("operating_model")
  if not isinstance(operating_model, dict):
    operating_model = {}

  parts: List[str] = []

  capacity_driver = str(operating_model.get("capacity_driver") or "").strip()
  if capacity_driver:
    parts.append(f"Capacity driver: {capacity_driver}")

  sales_modality = str(operating_model.get("sales_modality") or "").strip()
  if sales_modality:
    parts.append(f"Sales modality: {sales_modality}")

  timing_bits: List[str] = []
  start_date = str(business_start_date or operating_model.get("start_date") or "").strip()
  if start_date:
    timing_bits.append(f"start date {start_date}")

  milestones = _parse_milestones(operating_model.get("milestones"))
  milestones_summary = _summarize_milestones(milestones)
  if milestones_summary:
    timing_bits.append(f"milestones {milestones_summary}")

  if timing_bits:
    parts.append("Timing: " + "; ".join(timing_bits))

  utilization_lines = _build_utilization_summary(financials_year1_json)
  if utilization_lines:
    parts.append("Utilization/volume: " + "; ".join(utilization_lines))

  if not parts:
    return ""

  lines = ["Operational constraints:"] + [f"- {part}" for part in parts]
  return "\n".join(lines)


def build_revenue_math_line(
  financials_year1_json: Dict[str, Any],
  unit_name: Optional[str] = None,
) -> str:
  def _escape_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").strip()

  def _capacity_display(obj: Dict[str, Any], fallback_unit_name: Optional[str] = None) -> str:
    cadence = _normalize_cadence(obj.get("unit_cadence"))
    period_label = _cadence_label(cadence)
    unit_label = str(obj.get("unit_name") or "").strip() or str(fallback_unit_name or "").strip() or "units"

    if cadence == "contract":
      capacity_val = obj.get("units_per_period_capacity")
      if _to_float(capacity_val) is None:
        capacity_val = obj.get("units_per_week_capacity")
      capacity = _format_number(capacity_val)
      return f"{capacity} active {unit_label}"

    capacity_val = obj.get("units_per_period_capacity")
    if _to_float(capacity_val) is None:
      capacity_val = obj.get("units_per_week_capacity")
      period_label = "week"
    capacity = _format_number(capacity_val)
    return f"{capacity} {unit_label}/{period_label}"

  def _utilization_display(obj: Dict[str, Any]) -> str:
    utilization_rate = _normalize_utilization(obj.get("utilization_rate"))
    if utilization_rate is None:
      return ""
    return _format_percent(utilization_rate)

  def _periods_display(obj: Dict[str, Any]) -> str:
    cadence = _normalize_cadence(obj.get("unit_cadence"))
    periods_val = obj.get("operating_periods_per_year")
    if _to_float(periods_val) is None:
      periods_val = obj.get("operating_weeks_per_year")
    if cadence == "contract":
      periods_num = _to_float(periods_val)
      if periods_num is None or periods_num <= 0:
        return ""
    periods = _format_number(periods_val)
    if cadence == "contract":
      return f"~{periods} turns/year"
    return periods

  def _utilization_header() -> str:
    return "Load / Utilization"

  lobs = financials_year1_json.get("lobs")
  if not isinstance(lobs, list):
    line_of_business = str(financials_year1_json.get("lob_name") or "").strip() or "Company"
    product_name = str(financials_year1_json.get("product_name") or "").strip() or (
      str(unit_name or "").strip() or "Product"
    )
    rows = [
      f"| Line of Business | Product / Unit | Capacity | {_utilization_header()} | Price | Periods / Year | Year-1 Revenue |",
      "| --- | --- | --- | --- | --- | --- | --- |",
      (
        f"| {_escape_cell(line_of_business)} | {_escape_cell(product_name)} | "
        f"{_escape_cell(_capacity_display(financials_year1_json, unit_name))} | "
        f"{_escape_cell(_utilization_display(financials_year1_json))} | "
        f"{_escape_cell(_format_currency(financials_year1_json.get('unit_price')))} | "
        f"{_escape_cell(_periods_display(financials_year1_json))} | "
        f"{_escape_cell(_format_currency(financials_year1_json.get('revenue_total_year1')))} |"
      ),
      (
        f"| **Company Total** |  |  |  |  |  | "
        f"**{_escape_cell(_format_currency(financials_year1_json.get('revenue_total_year1')))}** |"
      ),
    ]
    return "\n".join(rows)

  lines: List[str] = [
    f"| Line of Business | Product / Unit | Capacity | {_utilization_header()} | Price | Periods / Year | Year-1 Revenue |",
    "| --- | --- | --- | --- | --- | --- | --- |",
  ]
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip() or "Line of business"
    products = lob.get("products")
    products = products if isinstance(products, list) else []
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip() or "Product"
      lines.append(
        f"| {_escape_cell(lob_name)} | {_escape_cell(product_name)} | "
        f"{_escape_cell(_capacity_display(product, unit_name))} | "
        f"{_escape_cell(_utilization_display(product))} | "
        f"{_escape_cell(_format_currency(product.get('unit_price')))} | "
        f"{_escape_cell(_periods_display(product))} | "
        f"{_escape_cell(_format_currency(product.get('revenue_total_year1')))} |"
      )
    lines.append(
      f"| **{_escape_cell(lob_name)} total** |  |  |  |  |  | "
      f"**{_escape_cell(_format_currency(lob.get('revenue_total_year1')))}** |"
    )

  lines.append(
    f"| **Company Total** |  |  |  |  |  | "
    f"**{_escape_cell(_format_currency(financials_year1_json.get('company_revenue_total_year1')))}** |"
  )
  return "\n".join([line for line in lines if line])


def _normalize_driver_value(value: Any) -> Any:
  num = _to_float(value)
  if num is None:
    if isinstance(value, str):
      return value.strip()
    return None
  return round(num, 6)


def build_revenue_driver_signature(financials_year1_json: Dict[str, Any]) -> str:
  lobs = financials_year1_json.get("lobs")
  snapshots: List[Dict[str, Any]] = []

  if not isinstance(lobs, list):
    cadence = _normalize_cadence(financials_year1_json.get("unit_cadence"))
    snapshots.append(
      {
        "unit_cadence": cadence,
        "driver_schema": _cadence_driver_schema(cadence),
        "cadence_metadata": financials_year1_json.get("cadence_metadata"),
        "unit_price": _normalize_driver_value(financials_year1_json.get("unit_price")),
        "units_per_week_capacity": _normalize_driver_value(
          financials_year1_json.get("units_per_week_capacity")
        ),
        "units_per_month_capacity": _normalize_driver_value(
          financials_year1_json.get("units_per_month_capacity")
        ),
        "concurrent_capacity_units": _normalize_driver_value(
          financials_year1_json.get("concurrent_capacity_units")
        ),
        "units_per_period_capacity": _normalize_driver_value(
          financials_year1_json.get("units_per_period_capacity")
        ),
        "avg_units_per_week_year1": _normalize_driver_value(
          financials_year1_json.get("avg_units_per_week_year1")
        ),
        "avg_units_per_month_year1": _normalize_driver_value(
          financials_year1_json.get("avg_units_per_month_year1")
        ),
        "avg_units_per_period_year1": _normalize_driver_value(
          financials_year1_json.get("avg_units_per_period_year1")
        ),
        "operating_weeks_per_year": _normalize_driver_value(
          financials_year1_json.get("operating_weeks_per_year")
        ),
        "operating_periods_per_year": _normalize_driver_value(
          financials_year1_json.get("operating_periods_per_year")
        ),
        "annual_units_year1": _normalize_driver_value(financials_year1_json.get("annual_units_year1")),
        "avg_active_units_year1": _normalize_driver_value(financials_year1_json.get("avg_active_units_year1")),
        "annual_turns_per_year": _normalize_driver_value(financials_year1_json.get("annual_turns_per_year")),
        "annual_completed_units_year1": _normalize_driver_value(financials_year1_json.get("annual_completed_units_year1")),
      }
    )
    return json.dumps(snapshots, sort_keys=True, ensure_ascii=False)

  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip()
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip()
      cadence = _normalize_cadence(product.get("unit_cadence"))
      snapshots.append(
        {
          "lob_name": lob_name,
          "product_name": product_name,
          "unit_cadence": cadence,
          "driver_schema": _cadence_driver_schema(cadence),
          "cadence_metadata": product.get("cadence_metadata"),
          "unit_price": _normalize_driver_value(product.get("unit_price")),
          "units_per_week_capacity": _normalize_driver_value(
            product.get("units_per_week_capacity")
          ),
          "units_per_month_capacity": _normalize_driver_value(
            product.get("units_per_month_capacity")
          ),
          "concurrent_capacity_units": _normalize_driver_value(
            product.get("concurrent_capacity_units")
          ),
          "units_per_period_capacity": _normalize_driver_value(
            product.get("units_per_period_capacity")
          ),
          "avg_units_per_week_year1": _normalize_driver_value(
            product.get("avg_units_per_week_year1")
          ),
          "avg_units_per_month_year1": _normalize_driver_value(
            product.get("avg_units_per_month_year1")
          ),
          "avg_units_per_period_year1": _normalize_driver_value(
            product.get("avg_units_per_period_year1")
          ),
          "operating_weeks_per_year": _normalize_driver_value(
            product.get("operating_weeks_per_year")
          ),
          "operating_periods_per_year": _normalize_driver_value(
            product.get("operating_periods_per_year")
          ),
          "annual_units_year1": _normalize_driver_value(product.get("annual_units_year1")),
          "avg_active_units_year1": _normalize_driver_value(product.get("avg_active_units_year1")),
          "annual_turns_per_year": _normalize_driver_value(product.get("annual_turns_per_year")),
          "annual_completed_units_year1": _normalize_driver_value(product.get("annual_completed_units_year1")),
        }
      )

  return json.dumps(snapshots, sort_keys=True, ensure_ascii=False)


def build_revenue_guardrail_signals(
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  *,
  business_start_date: Optional[str] = None,
  fulfillment_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  operating_model = shared_context.get("operating_model")
  if not isinstance(operating_model, dict):
    operating_model = {}
  people_context = shared_context.get("people_capability")
  if not isinstance(people_context, dict):
    people_context = {}
  market_context = shared_context.get("target_market")
  if not isinstance(market_context, dict):
    market_context = {}

  context_signals: List[str] = []

  business_stage = str(operating_model.get("business_stage") or "").strip()
  if business_stage:
    context_signals.append(f"business_stage: {business_stage}")

  capacity_driver = str(operating_model.get("capacity_driver") or "").strip()
  if capacity_driver:
    context_signals.append(f"capacity_driver: {capacity_driver}")

  sales_modality = str(operating_model.get("sales_modality") or "").strip()
  if sales_modality:
    context_signals.append(f"sales_modality: {sales_modality}")

  start_date = str(business_start_date or operating_model.get("start_date") or "").strip()
  if start_date:
    context_signals.append(f"start_date: {start_date}")

  milestones = _summarize_milestones(_parse_milestones(operating_model.get("milestones")))
  if milestones:
    context_signals.append(f"milestones: {milestones}")

  marketing_summary = str(market_context.get("marketing_plan_summary") or "").strip()
  if marketing_summary:
    context_signals.append("marketing_plan: present")
  else:
    context_signals.append("marketing_plan: missing")

  if people_context.get("people"):
    context_signals.append("people_context: present")
  else:
    context_signals.append("people_context: missing")

  if isinstance(fulfillment_context, dict):
    fulfillment_time = str(fulfillment_context.get("time") or "").strip()
    fulfillment_personnel = str(fulfillment_context.get("personnel") or "").strip()
    if fulfillment_time:
      context_signals.append(f"fulfillment_time: {fulfillment_time}")
    if fulfillment_personnel:
      context_signals.append(f"fulfillment_personnel: {fulfillment_personnel}")

  product_signals: List[Dict[str, Any]] = []
  triggered = False

  lobs = financials_year1_json.get("lobs")
  lobs = lobs if isinstance(lobs, list) else []
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip()
    products = lob.get("products")
    products = products if isinstance(products, list) else []
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip()
      unit_cadence = _normalize_cadence(product.get("unit_cadence"))
      avg_units = _to_float(product.get("avg_units_per_period_year1"))
      if avg_units is None:
        avg_units = _to_float(product.get("avg_units_per_week_year1"))
      capacity = _to_float(product.get("units_per_period_capacity"))
      if capacity is None:
        capacity = _to_float(product.get("units_per_week_capacity"))
      utilization = None
      if capacity is not None and capacity > 0 and avg_units is not None:
        utilization = avg_units / capacity

      product_signals.append(
        {
          "lob_name": lob_name,
          "product_name": product_name,
          "unit_cadence": unit_cadence,
          "avg_units_per_period_year1": avg_units,
          "units_per_period_capacity": capacity,
          "operating_periods_per_year": _to_float(product.get("operating_periods_per_year")),
          "unit_price": _to_float(product.get("unit_price")),
          "utilization_ratio": utilization,
        }
      )

      if avg_units is None:
        continue
      if capacity is not None and capacity > 0:
        if avg_units > capacity:
          triggered = True
          continue
        if utilization is not None and utilization >= 0.9:
          triggered = True
          continue
        if utilization is not None and utilization >= 0.75:
          if business_stage in ("pre-revenue", "early-stage"):
            triggered = True
            continue
          if "people_context: missing" in context_signals or "marketing_plan: missing" in context_signals:
            triggered = True
            continue
      elif business_stage in ("pre-revenue", "early-stage"):
        triggered = True

  return {
    "triggered": triggered,
    "context_signals": context_signals,
    "product_signals": product_signals,
  }
