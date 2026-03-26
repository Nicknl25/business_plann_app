from __future__ import annotations

from typing import Any, Dict, Optional

try:
  from planning_contract import PLANNING_CONTRACT_VERSION  # type: ignore
except Exception:
  from client_intake_and_finmo.planning_contract import PLANNING_CONTRACT_VERSION  # type: ignore

try:
  from solver_trace import trace_lazy  # type: ignore
except Exception:
  from client_intake_and_finmo.solver_trace import trace_lazy  # type: ignore


CONSTRAINT_TRAITS_VERSION = "constraint-traits/v3"


def _clean_text(value: Any) -> str:
  return " ".join(str(value or "").strip().split())


def _norm_token(value: Any) -> str:
  return _clean_text(value).lower()


def _normalize_naics_6(value: Any) -> Optional[str]:
  digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
  return digits[:6] if len(digits) >= 6 else None


def resolve_business_classification(
  *,
  conn=None,
  shared_context: Optional[Dict[str, Any]] = None,
  operating_model: Optional[Dict[str, Any]] = None,
  business_type: Optional[str] = None,
  naics_6: Optional[str] = None,
) -> Dict[str, Any]:
  del conn
  context = shared_context if isinstance(shared_context, dict) else {}
  ops = operating_model if isinstance(operating_model, dict) else dict(context.get("operating_model") or {})
  persisted_business_type = _clean_text(business_type or ops.get("business_type")) or None
  normalized_naics = _normalize_naics_6(naics_6 or ops.get("business_naics_6"))
  if not normalized_naics and not persisted_business_type:
    return {
      "naics_6": None,
      "business_type": None,
      "source": "none",
    }
  return {
    "naics_6": normalized_naics,
    "business_type": persisted_business_type,
    "source": "persisted_business_type" if (normalized_naics or persisted_business_type) else "none",
  }


def _normalize_customer_type(value: Any) -> Optional[str]:
  token = _norm_token(value)
  if token in {"consumer", "b2c"}:
    return "b2c"
  if token == "b2b":
    return "b2b"
  if token == "mixed":
    return "mixed"
  return None


def _normalize_sales_modality(value: Any) -> Optional[str]:
  token = _norm_token(value)
  if not token:
    return None
  flags = {
    "retail": any(word in token for word in ("retail", "storefront", "shop", "in-store", "in store")),
    "online": any(word in token for word in ("online", "digital", "e-commerce", "ecommerce", "web")),
    "manufacturing": any(word in token for word in ("manufactur", "factory", "production", "fabricat")),
    "project_based": any(word in token for word in ("project", "contract", "engagement", "case")),
    "local_service": any(word in token for word in ("service", "onsite", "on-site", "in person", "field")),
  }
  enabled = [name for name, active in flags.items() if active]
  if len(enabled) >= 2:
    return "hybrid"
  if enabled:
    return enabled[0]
  return None


def _normalize_capacity_driver(value: Any) -> Optional[str]:
  token = _norm_token(value)
  if not token:
    return None
  if "labor" in token or "staff" in token or "crew" in token:
    return "labor"
  if "system" in token or "software" in token or "platform" in token or "automation" in token:
    return "system"
  if "space" in token or "seat" in token or "room" in token or "location" in token:
    return "space"
  if "equipment" in token or "machine" in token or "vehicle" in token or "tool" in token:
    return "equipment"
  if "demand" in token or "traffic" in token or "lead" in token:
    return "demand"
  return None


def _normalize_unit_cadence(value: Any) -> Optional[str]:
  token = _norm_token(value)
  if not token:
    return None
  if "season" in token:
    return "seasonal"
  if any(word in token for word in ("project", "engagement", "case")):
    return "project"
  if any(word in token for word in ("contract", "retainer")):
    return "contract"
  if any(word in token for word in ("one-time", "one time", "single", "once")):
    return "one_time"
  if any(word in token for word in ("daily", "weekly", "monthly", "annual", "yearly", "subscription", "recurring", "repeat")):
    return "recurring"
  return None


def _normalize_geographic_scope(value: Any) -> Optional[str]:
  token = _norm_token(value)
  if not token:
    return None
  if any(word in token for word in ("international", "global", "worldwide")):
    return "international"
  if "national" in token or "nationwide" in token:
    return "national"
  if "regional" in token or "multi-state" in token or "multistate" in token:
    return "regional"
  if "local" in token or "city" in token or "metro" in token:
    return "local"
  return None


def _normalize_business_stage(value: Any) -> Optional[str]:
  token = _norm_token(value)
  if not token:
    return None
  if "pre" in token and "revenue" in token:
    return "pre_revenue"
  if "early" in token or "startup" in token or "launch" in token:
    return "startup"
  if "operat" in token or "live" in token or "active" in token:
    return "operating"
  if "growth" in token or "scale" in token:
    return "growth"
  if "mature" in token or "established" in token:
    return "mature"
  return None


def _normalize_fulfillment_shape(*, shipping_method: Any, sales_modality: Any, fulfillment_json: Optional[Dict[str, Any]]) -> Optional[str]:
  shipping = _norm_token(shipping_method)
  modality = _norm_token(sales_modality)
  personnel = _norm_token((fulfillment_json or {}).get("personnel"))
  timing = _norm_token((fulfillment_json or {}).get("time"))
  text = " ".join(part for part in (shipping, modality, personnel, timing) if part).strip()
  if not text:
    return None
  if any(word in text for word in ("digital", "download", "software", "platform", "remote")):
    return "digital_remote"
  if any(word in text for word in ("ship", "shipping", "mail", "carrier", "freight")):
    return "shipped_goods"
  if any(word in text for word in ("pickup", "counter", "walk-in", "walk in")):
    return "onsite_pickup"
  if any(word in text for word in ("install", "site visit", "onsite service", "on-site service")):
    return "installed_service"
  if any(word in text for word in ("deliver", "delivery", "courier")):
    return "local_delivery"
  if any(word in text for word in ("service", "crew", "technician", "owner")):
    return "onsite_service"
  return None


def _first_year1_cadence(financials_year1_json: Optional[Dict[str, Any]]) -> Optional[str]:
  obj = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  direct = _normalize_unit_cadence(obj.get("unit_cadence"))
  if direct:
    return direct
  lobs = obj.get("lobs")
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
      cadence = _normalize_unit_cadence(product.get("unit_cadence"))
      if cadence:
        return cadence
  return None


def extract_normalized_traits(
  *,
  conn=None,
  shared_context: Optional[Dict[str, Any]] = None,
  operating_model: Optional[Dict[str, Any]] = None,
  target_market: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  fulfillment_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  context = shared_context if isinstance(shared_context, dict) else {}
  ops = operating_model if isinstance(operating_model, dict) else dict(context.get("operating_model") or {})
  market = target_market if isinstance(target_market, dict) else dict(context.get("target_market") or {})
  year1 = (
    financials_year1_json
    if isinstance(financials_year1_json, dict)
    else dict(context.get("financials_year1_json") or {})
  )
  fulfillment = (
    fulfillment_json if isinstance(fulfillment_json, dict) else dict(context.get("fulfillment_json") or {})
  )

  classification = resolve_business_classification(
    conn=conn,
    shared_context=context,
    operating_model=ops,
  )
  naics_6 = _normalize_naics_6(classification.get("naics_6"))
  business_type = _clean_text(classification.get("business_type")) or None

  traits = {
    "contract_version": PLANNING_CONTRACT_VERSION,
    "traits_version": CONSTRAINT_TRAITS_VERSION,
    "naics_6": naics_6,
    "business_type": business_type,
    "industry": None,
    "sector": None,
    "classification_source": str(classification.get("source") or "none"),
    "customer_type": _normalize_customer_type(market.get("consumer_type") or ops.get("consumer_type")),
    "sales_modality": _normalize_sales_modality(ops.get("sales_modality")),
    "capacity_driver": _normalize_capacity_driver(ops.get("capacity_driver")),
    "unit_cadence": _normalize_unit_cadence(ops.get("unit_cadence")) or _first_year1_cadence(year1),
    "geographic_scope": _normalize_geographic_scope(ops.get("geographic_scope")),
    "business_stage": _normalize_business_stage(ops.get("business_stage")),
    "fulfillment_shape": _normalize_fulfillment_shape(
      shipping_method=ops.get("shipping_method"),
      sales_modality=ops.get("sales_modality"),
      fulfillment_json=fulfillment,
    ),
  }
  trace_lazy(
    "TRAITS",
    "Normalized trait extraction",
    lambda: {
      "classification": classification,
      "traits": traits,
      "ops_keys": sorted(list(ops.keys())),
      "market_keys": sorted(list(market.keys())),
      "year1_has_lobs": bool(year1.get("lobs")),
    },
  )
  return traits
