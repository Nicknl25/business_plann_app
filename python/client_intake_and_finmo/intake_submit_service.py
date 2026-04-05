from __future__ import annotations

import json
from typing import Any, Dict, Optional

from client_intake_and_finmo.business_type_naics import get_naics_from_business_type
from client_intake_and_finmo.intake_submission import (
  generate_client_id,
  get_mysql_connection,
  insert_intake_submission,
  parse_business_start_date,
  send_intake_confirmation_email,
)


class IntakeValidationError(Exception):
  def __init__(self, errors: Dict[str, str]):
    super().__init__("invalid_request")
    self.errors = errors


def _parse_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


def _normalize_lease_period(value: Any) -> str:
  raw = "" if value is None else str(value).strip().lower()
  if not raw:
    return "unknown"
  if raw in ("none", "no", "n/a", "na", "0", "zero"):
    return "none"
  aliases = {
    "month": "monthly",
    "monthly": "monthly",
    "per month": "monthly",
    "mo": "monthly",
    "week": "weekly",
    "weekly": "weekly",
    "per week": "weekly",
    "wk": "weekly",
    "biweekly": "biweekly",
    "bi-weekly": "biweekly",
    "every two weeks": "biweekly",
    "quarter": "quarterly",
    "quarterly": "quarterly",
    "per quarter": "quarterly",
    "year": "annually",
    "annual": "annually",
    "annually": "annually",
    "per year": "annually",
    "semiannual": "semiannually",
    "semi-annually": "semiannually",
    "semiannually": "semiannually",
  }
  for key, normalized in aliases.items():
    if raw == key:
      return normalized
  for key, normalized in aliases.items():
    if key in raw:
      return normalized
  return raw


def _format_float_compact(value: float) -> str:
  try:
    if float(value).is_integer():
      return str(int(value))
  except Exception:
    pass
  return f"{float(value):g}"


def _normalize_initial_lease(value: Any) -> float:
  amount_val = _parse_float(value)
  if amount_val is None or amount_val < 0:
    return 0.0
  return float(amount_val)


def _normalize_capacity_driver(value: Any) -> Optional[str]:
  if value is None:
    return None
  raw = str(value).strip().lower()
  if not raw:
    return None
  if raw in ("labor", "system", "demand"):
    return raw
  if "labor" in raw or "staff" in raw or "chair" in raw or "hours" in raw:
    return "labor"
  if "system" in raw or "process" in raw or "equipment" in raw or "space" in raw:
    return "system"
  if "demand" in raw or "customer" in raw or "clients" in raw or "leads" in raw:
    return "demand"
  return None


def _normalize_sales_modality(value: Any) -> Optional[str]:
  if value is None:
    return None
  raw = str(value).strip().lower()
  if not raw:
    return None
  if raw in ("physical", "in-person", "in person", "offline"):
    return "physical"
  if raw in ("online", "digital", "virtual", "ecommerce", "e-commerce", "web"):
    return "online"
  if raw == "hybrid":
    return "hybrid"
  has_online = any(token in raw for token in ("online", "digital", "virtual", "e-comm", "ecomm", "website", "web"))
  has_physical = any(token in raw for token in ("in-person", "in person", "physical", "store", "shop", "location", "on-site", "onsite"))
  if has_online and has_physical:
    return "hybrid"
  if has_online:
    return "online"
  if has_physical:
    return "physical"
  return None


def _normalize_geographic_scope(value: Any) -> Optional[str]:
  if value is None:
    return None
  raw = str(value).strip().lower()
  if not raw:
    return None
  if raw in ("local", "regional", "national", "international"):
    return raw
  if "international" in raw or "global" in raw or "world" in raw:
    return "international"
  if "national" in raw or "nationwide" in raw or "country" in raw or raw == "usa" or raw == "us":
    return "national"
  if "regional" in raw or "state" in raw or "multi-city" in raw or "multiple cities" in raw:
    return "regional"
  if "local" in raw or "nearby" in raw or "neighborhood" in raw or "town" in raw or "city" in raw:
    return "local"
  return None


def _normalize_consumer_type(value: Any) -> Optional[str]:
  if value is None:
    return None
  raw = str(value).strip().lower()
  if not raw:
    return None
  if raw in ("consumer", "b2b", "mixed"):
    return raw
  if "b2b" in raw or "business" in raw:
    if "both" in raw or "mixed" in raw or "and" in raw:
      return "mixed"
    return "b2b"
  if "consumer" in raw or "b2c" in raw:
    if "both" in raw or "mixed" in raw or "and" in raw:
      return "mixed"
    return "consumer"
  return None


def _normalize_legal_entity(value: Any) -> str:
  raw = "" if value is None else str(value).strip().lower()
  if not raw:
    return "Sole proprietor"
  if "llc" in raw or "limited liability company" in raw:
    return "LLC"
  if "llp" in raw or "limited liability partnership" in raw:
    return "LLP"
  if "s-corp" in raw or "s corp" in raw or "scorp" in raw:
    return "S-corp"
  if "c-corp" in raw or "c corp" in raw or "ccorp" in raw:
    return "C-corp"
  if "partnership" in raw:
    return "Partnership"
  if "sole" in raw and ("prop" in raw or "propriet" in raw):
    return "Sole proprietor"
  return "Sole proprietor"


def process_intake_submission(payload: Dict[str, Any]) -> Dict[str, Any]:
  errors: Dict[str, str] = {}

  consumer_type_raw = payload.get("consumer_type")
  consumer_type = _normalize_consumer_type(consumer_type_raw)
  if not consumer_type:
    errors["consumer_type"] = "consumer_type is required (consumer, b2b, or mixed)"

  client_id_raw = payload.get("client_id")
  if not client_id_raw or not str(client_id_raw).strip():
    errors["client_id"] = "client_id is required"
  client_id = str(client_id_raw).strip() if client_id_raw else ""

  business_type = payload.get("business_type")
  if not business_type or not str(business_type).strip():
    errors["business_type"] = "business_type is required"

  lob_models = payload.get("lob_models")
  if isinstance(lob_models, str):
    try:
      lob_models = json.loads(lob_models)
    except Exception:
      lob_models = None
  is_multi_lob = False
  if isinstance(lob_models, list) and lob_models:
    if len(lob_models) > 1:
      is_multi_lob = True
    else:
      try:
        products = lob_models[0].get("products") if isinstance(lob_models[0], dict) else None
        if isinstance(products, list) and len(products) > 1:
          is_multi_lob = True
      except Exception:
        pass

  revenue_value = _parse_float(payload.get("current_revenue"))
  if revenue_value is None:
    errors["current_revenue"] = "current_revenue must be a number"

  required_text_fields = (
    "business_name",
    "business_type",
    "target_market_summary",
    "key_people_summary",
    "first_name",
    "last_name",
    "email_address",
    "business_start_date",
  )
  for key in required_text_fields:
    if payload.get(key) is None or not str(payload.get(key)).strip():
      errors[key] = f"{key} is required"

  if consumer_type in ("consumer", "mixed"):
    if payload.get("target_market") is None or not str(payload.get("target_market")).strip():
      errors["target_market"] = "target_market is required"

  if consumer_type in ("b2b", "mixed"):
    for key in ("target_market_b2b_industry", "target_market_b2b_size", "target_market_b2b_age"):
      if payload.get(key) is None or not str(payload.get(key)).strip():
        errors[key] = f"{key} is required"

  try:
    business_start_date = parse_business_start_date(payload.get("business_start_date"))
  except Exception as exc:
    errors["business_start_date"] = str(exc)
    business_start_date = None  # type: ignore

  if errors:
    raise IntakeValidationError(errors)

  row: Dict[str, Any] = dict(payload)
  row["client_id"] = client_id or generate_client_id()
  if consumer_type:
    row["consumer_type"] = consumer_type
  row["business_start_date"] = business_start_date
  row["current_revenue"] = revenue_value

  if consumer_type == "consumer":
    row["target_market_b2b_industry"] = None
    row["target_market_b2b_size"] = None
    row["target_market_b2b_age"] = None
  if consumer_type == "b2b":
    row["target_market"] = None

  normalized_legal_entity = _normalize_legal_entity(payload.get("legal_entity"))
  row["legal_entity"] = normalized_legal_entity
  if payload.get("legal_entity") is None or not str(payload.get("legal_entity")).strip():
    payload["legal_entity"] = normalized_legal_entity

  for key in (
    "description",
    "product_keywords",
    "customer_age_range",
    "customer_income_level",
    "customer_type",
    "customer_additional_details",
    "pricing_model",
    "founder_background",
  ):
    if row.get(key) is None:
      row[key] = ""

  operating_required = [
    "consumer_type",
    "shipping_method",
    "sales_modality",
    "geographic_scope",
    "geographic_coverage",
    "countries",
    "milestones",
    "capacity_driver",
    "primary_growth_lever",
    "legal_entity",
    "business_description_summary",
  ]
  if not is_multi_lob:
    operating_required.extend(["unit_name", "unit_description", "units_per_week_capacity", "unit_price"])
  for key in operating_required:
    if payload.get(key) is None or payload.get(key) == "":
      errors[key] = f"{key} is required"

  normalized_capacity_driver = _normalize_capacity_driver(payload.get("capacity_driver"))
  if not normalized_capacity_driver:
    errors["capacity_driver"] = "capacity_driver must be one of: labor, system, demand"
  else:
    row["capacity_driver"] = normalized_capacity_driver

  normalized_sales_modality = _normalize_sales_modality(payload.get("sales_modality"))
  if not normalized_sales_modality:
    errors["sales_modality"] = "sales_modality must be one of: physical, online, hybrid"
  else:
    row["sales_modality"] = normalized_sales_modality

  normalized_scope = _normalize_geographic_scope(payload.get("geographic_scope"))
  if not normalized_scope:
    errors["geographic_scope"] = "geographic_scope must be one of: local, regional, national, international"
  else:
    row["geographic_scope"] = normalized_scope

  geographic_coverage = payload.get("geographic_coverage")
  if geographic_coverage is None or str(geographic_coverage).strip() == "":
    errors["geographic_coverage"] = "geographic_coverage is required"
  else:
    row["geographic_coverage"] = str(geographic_coverage).strip()

  if payload.get("units_per_week_capacity") not in (None, ""):
    try:
      row["units_per_week_capacity"] = float(payload.get("units_per_week_capacity"))
    except Exception:
      errors["units_per_week_capacity"] = "units_per_week_capacity must be a number"
  elif not is_multi_lob:
    errors["units_per_week_capacity"] = "units_per_week_capacity must be a number"

  if payload.get("unit_price") not in (None, ""):
    try:
      row["unit_price"] = float(payload.get("unit_price"))
    except Exception:
      errors["unit_price"] = "unit_price must be a number"
    else:
      if row["unit_price"] <= 0:
        errors["unit_price"] = "unit_price must be greater than 0"
  elif not is_multi_lob:
    errors["unit_price"] = "unit_price must be a number"

  assets_val = _parse_float(payload.get("initial_assets"))
  row["initial_assets"] = float(assets_val if assets_val is not None and assets_val >= 0 else 0.0)
  row["initial_lease"] = _normalize_initial_lease(payload.get("initial_lease"))
  equity_val = _parse_float(payload.get("initial_equity"))
  row["initial_equity"] = float(equity_val if equity_val is not None and equity_val >= 0 else 0.0)

  for key in ("countries", "milestones"):
    val = payload.get(key)
    row[key] = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)

  try:
    milestones_val = payload.get("milestones")
    if isinstance(milestones_val, str):
      milestones_val = json.loads(milestones_val)
    if not isinstance(milestones_val, list) or len(milestones_val) == 0:
      errors["milestones"] = "At least one future milestone is required"
    else:
      for idx, milestone in enumerate(milestones_val):
        if not isinstance(milestone, dict):
          errors["milestones"] = "milestones must be a list of {description, timing}"
          break
        if not str(milestone.get("description") or "").strip():
          errors["milestones"] = f"milestones[{idx}].description is required"
          break
        if not str(milestone.get("timing") or "").strip():
          errors["milestones"] = f"milestones[{idx}].timing is required"
          break
  except Exception:
    errors["milestones"] = "milestones must be valid JSON"

  confidence = payload.get("operating_model_confidence", None)
  if confidence is not None and confidence != "":
    try:
      row["operating_model_confidence"] = float(confidence)
    except Exception:
      errors["operating_model_confidence"] = "operating_model_confidence must be a number"

  if errors:
    raise IntakeValidationError(errors)

  conn = get_mysql_connection()
  try:
    try:
      row["naics_code"] = get_naics_from_business_type(conn, str(business_type).strip())
    except Exception as exc:
      raise IntakeValidationError({"business_type": str(exc)}) from exc

    inserted = insert_intake_submission(conn=conn, row=row)
    if not inserted or not inserted.get("inserted_id"):
      raise RuntimeError("Failed to write intake submission.")
  finally:
    try:
      conn.close()
    except Exception:
      pass

  try:
    email_result = send_intake_confirmation_email(
      to_email=str(payload.get("email_address") or "").strip(),
      first_name=str(payload.get("first_name") or "").strip(),
      last_name=str(payload.get("last_name") or "").strip(),
      client_id=row["client_id"],
    )
  except Exception as exc:
    email_result = {"sent": False, "reason": str(exc)}

  return {
    "status": "ok",
    "intake_submission_id": inserted.get("inserted_id"),
    "client_id": row["client_id"],
    "naics_code": row.get("naics_code"),
    "email": email_result,
  }
