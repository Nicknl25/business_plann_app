from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_OPERATING_WEEKS_PER_YEAR = 52.0


def _to_float(value: Any) -> Optional[float]:
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
  return [
    {
      "lob_name": lob_name,
      "products": [
        {
          "product_name": product_name,
          "unit_name": unit_name,
          "unit_description": str(operating_model.get("unit_description") or "").strip(),
          "unit_price": operating_model.get("unit_price"),
          "units_per_week_capacity": operating_model.get("units_per_week_capacity"),
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
      products.append(
        {
          "product_name": product_name,
          "unit_name": unit_name,
          "unit_description": str(product.get("unit_description") or "").strip()
          or str(operating_model.get("unit_description") or "").strip(),
          "unit_price": product.get("unit_price"),
          "units_per_week_capacity": product.get("units_per_week_capacity"),
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


def _apply_override_value(raw: Any, fallback: Any) -> Any:
  return raw if raw is not None else fallback


def _apply_product_drivers(
  *,
  base_product: Dict[str, Any],
  override: Dict[str, Any],
  global_override: Dict[str, Any],
) -> Dict[str, Any]:
  unit_price = _apply_override_value(override.get("unit_price"), base_product.get("unit_price"))
  unit_price = _apply_override_value(global_override.get("unit_price"), unit_price)
  unit_price = _nonnegative(_to_float(unit_price)) or 0.0

  units_per_week_capacity = _apply_override_value(
    override.get("units_per_week_capacity"), base_product.get("units_per_week_capacity")
  )
  units_per_week_capacity = _apply_override_value(
    global_override.get("units_per_week_capacity"), units_per_week_capacity
  )
  units_per_week_capacity = _nonnegative(_to_float(units_per_week_capacity)) or 0.0

  operating_weeks_per_year = _apply_override_value(
    override.get("operating_weeks_per_year"), global_override.get("operating_weeks_per_year")
  )
  operating_weeks_per_year = _nonnegative(_to_float(operating_weeks_per_year))
  if operating_weeks_per_year is None or operating_weeks_per_year <= 0:
    operating_weeks_per_year = DEFAULT_OPERATING_WEEKS_PER_YEAR

  utilization_rate = _apply_override_value(override.get("utilization_rate"), global_override.get("utilization_rate"))
  utilization_rate = _normalize_utilization(utilization_rate)

  avg_units_per_week_year1 = _apply_override_value(
    override.get("avg_units_per_week_year1"), global_override.get("avg_units_per_week_year1")
  )
  avg_units_per_week_year1 = _nonnegative(_to_float(avg_units_per_week_year1))
  if avg_units_per_week_year1 is None:
    if utilization_rate is not None:
      avg_units_per_week_year1 = utilization_rate * units_per_week_capacity
    else:
      avg_units_per_week_year1 = units_per_week_capacity

  revenue_total_year1 = avg_units_per_week_year1 * operating_weeks_per_year * unit_price

  out = dict(base_product)
  out["unit_price"] = float(unit_price)
  out["units_per_week_capacity"] = float(units_per_week_capacity)
  out["avg_units_per_week_year1"] = float(avg_units_per_week_year1)
  out["operating_weeks_per_year"] = float(operating_weeks_per_year)
  if utilization_rate is not None:
    out["utilization_rate"] = float(utilization_rate)
  out["revenue_total_year1"] = float(revenue_total_year1)
  return out


def assemble_financials_year1(
  shared_context: Dict[str, Any],
  existing_year1: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  existing = existing_year1 if isinstance(existing_year1, dict) else {}
  operating_model = shared_context.get("operating_model")
  if not isinstance(operating_model, dict):
    operating_model = {}

  base_lobs = _build_base_lobs(operating_model)
  by_key, by_name = _build_existing_product_map(existing)

  global_override = {
    "unit_price": existing.get("unit_price"),
    "units_per_week_capacity": existing.get("units_per_week_capacity"),
    "avg_units_per_week_year1": existing.get("avg_units_per_week_year1"),
    "operating_weeks_per_year": existing.get("operating_weeks_per_year"),
    "utilization_rate": existing.get("utilization_rate"),
  }

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
        global_override=global_override,
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

  if "unit_price" in patch:
    next_product["unit_price"] = _nonnegative(_to_float(patch.get("unit_price"))) or 0.0
  if "units_per_week_capacity" in patch:
    next_product["units_per_week_capacity"] = _nonnegative(
      _to_float(patch.get("units_per_week_capacity"))
    ) or 0.0
  if "operating_weeks_per_year" in patch:
    next_product["operating_weeks_per_year"] = _nonnegative(
      _to_float(patch.get("operating_weeks_per_year"))
    ) or 0.0
  if "avg_units_per_week_year1" in patch:
    next_product["avg_units_per_week_year1"] = _nonnegative(
      _to_float(patch.get("avg_units_per_week_year1"))
    ) or 0.0
  if "utilization_rate" in patch:
    util = _normalize_utilization(patch.get("utilization_rate"))
    if util is not None:
      next_product["utilization_rate"] = util

  units_per_week_capacity = _nonnegative(_to_float(next_product.get("units_per_week_capacity"))) or 0.0
  operating_weeks_per_year = _nonnegative(_to_float(next_product.get("operating_weeks_per_year"))) or 0.0
  unit_price = _nonnegative(_to_float(next_product.get("unit_price"))) or 0.0

  avg_units_per_week_year1 = _nonnegative(_to_float(next_product.get("avg_units_per_week_year1")))
  if avg_units_per_week_year1 is None:
    avg_units_per_week_year1 = units_per_week_capacity

  if "utilization_rate" in next_product and "avg_units_per_week_year1" not in patch:
    util = _normalize_utilization(next_product.get("utilization_rate"))
    if util is not None:
      avg_units_per_week_year1 = util * units_per_week_capacity

  next_product["avg_units_per_week_year1"] = float(avg_units_per_week_year1)
  next_product["operating_weeks_per_year"] = float(operating_weeks_per_year)
  next_product["units_per_week_capacity"] = float(units_per_week_capacity)
  next_product["unit_price"] = float(unit_price)
  next_product["revenue_total_year1"] = float(
    avg_units_per_week_year1 * operating_weeks_per_year * unit_price
  )
  return next_product


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
  overrides_by_name = {
    _normalize_name(name): value
    for name, value in product_overrides.items()
    if isinstance(value, dict)
  }

  global_patch = {
    key: patch[key]
    for key in (
      "unit_price",
      "units_per_week_capacity",
      "avg_units_per_week_year1",
      "operating_weeks_per_year",
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
      override = overrides_by_name.get(_normalize_name(product_name))
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
      avg_units_val = _to_float(product.get("avg_units_per_week_year1"))
      capacity_val = _to_float(product.get("units_per_week_capacity"))
      utilization_rate = _normalize_utilization(product.get("utilization_rate"))

      if avg_units_val is None and capacity_val is None and utilization_rate is None:
        continue

      if avg_units_val is not None and capacity_val is not None:
        avg_units = _format_number(avg_units_val)
        capacity = _format_number(capacity_val)
        line = f"{product_name}: avg {avg_units} {unit_label}/week on {capacity} {unit_label}/week capacity"
      elif utilization_rate is not None:
        line = f"{product_name}: {_format_percent(utilization_rate)} utilization"
      elif avg_units_val is not None:
        avg_units = _format_number(avg_units_val)
        line = f"{product_name}: avg {avg_units} {unit_label}/week"
      else:
        capacity = _format_number(capacity_val)
        line = f"{product_name}: capacity {capacity} {unit_label}/week"

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
  lobs = financials_year1_json.get("lobs")
  if not isinstance(lobs, list):
    avg_units = _format_number(financials_year1_json.get("avg_units_per_week_year1"))
    weeks = _format_number(financials_year1_json.get("operating_weeks_per_year"))
    unit_label = str(unit_name or "").strip() or "units"
    price = _format_currency(financials_year1_json.get("unit_price"))
    total = _format_currency(financials_year1_json.get("revenue_total_year1"))
    return f"{avg_units} {unit_label}/week x {weeks} weeks/year x {price} per {unit_label} = {total}"

  lines: List[str] = []
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
      unit_label = str(product.get("unit_name") or "").strip() or str(unit_name or "").strip() or "units"
      avg_units = _format_number(product.get("avg_units_per_week_year1"))
      weeks = _format_number(product.get("operating_weeks_per_year"))
      price = _format_currency(product.get("unit_price"))
      total = _format_currency(product.get("revenue_total_year1"))
      lines.append(
        f"{product_name}: {avg_units} {unit_label}/week x {weeks} weeks/year x {price} per {unit_label} = {total}"
      )
    lines.append(f"{lob_name} total: {_format_currency(lob.get('revenue_total_year1'))}")

  lines.append(
    f"Company total: {_format_currency(financials_year1_json.get('company_revenue_total_year1'))}"
  )
  return "\n".join([line for line in lines if line])
