from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional

from finmo_revenue import (
  sync_intake_revenue_to_finmo,
  write_soi_revenue_total_all_firms_to_finmo,
)
from intake_business_types import get_naics_from_business_type, populate_finmo
from intake_submission import (
  create_client_finmo_workbook,
  fetch_intake_submission_by_id,
  generate_client_id,
  get_mysql_connection,
  insert_intake_submission,
  parse_business_start_date,
  send_intake_confirmation_email,
  update_intake_submission_finmo_path,
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


def _normalize_capacity_driver(value: Any) -> Optional[str]:
  if value is None:
    return None
  raw = str(value).strip().lower()
  if not raw:
    return None
  # Accept short canonical values.
  if raw in ("labor", "system", "demand"):
    return raw
  # Accept descriptive strings and map to canonical.
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

  # Heuristics for descriptive strings.
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
  if "national" in raw or "nationwide" in raw or "country" in raw or "usa" in raw or "us" == raw:
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
  # Allow a few natural-language variants.
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
  """
  Normalize legal entity values to a short canonical label.

  Requirement: if the client cannot clearly identify the entity type,
  default to "Sole proprietor" (no "unknown/other" values).
  """
  raw = "" if value is None else str(value).strip().lower()
  if not raw:
    return "Sole proprietor"

  # Common canonical values.
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

  # Sole proprietorship variants.
  if "sole" in raw and ("prop" in raw or "propriet" in raw):
    return "Sole proprietor"

  # If it's ambiguous or not one of the supported values, default.
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

  # Consumer demographics are only required when the business targets consumers.
  if consumer_type in ("consumer", "mixed"):
    if payload.get("target_market") is None or not str(payload.get("target_market")).strip():
      errors["target_market"] = "target_market is required"

  # B2B firmographic segmentation is required when the business targets businesses.
  if consumer_type in ("b2b", "mixed"):
    b2b_required = (
      "target_market_b2b_industry",
      "target_market_b2b_size",
      "target_market_b2b_age",
    )
    for key in b2b_required:
      if payload.get(key) is None or not str(payload.get(key)).strip():
        errors[key] = f"{key} is required"

  try:
    business_start_date = parse_business_start_date(
      payload.get("business_start_date")
    )
  except Exception as exc:
    errors["business_start_date"] = str(exc)
    business_start_date = None  # type: ignore

  finmo_template_path = (os.getenv("FINMO") or "").strip()
  client_finmo_dir = (os.getenv("CLIENT_FINMO") or "").strip()
  if not finmo_template_path:
    errors["FINMO"] = "FINMO env var must point to the Excel template file."
  if not client_finmo_dir:
    errors["CLIENT_FINMO"] = (
      "CLIENT_FINMO env var must point to a folder for per-client workbooks."
    )

  if errors:
    raise IntakeValidationError(errors)

  row: Dict[str, Any] = dict(payload)
  row["client_id"] = client_id
  if consumer_type:
    row["consumer_type"] = consumer_type
  row["business_start_date"] = business_start_date
  row["current_revenue"] = revenue_value

  # Normalize target-market storage based on consumer_type so we don't persist blanks.
  if consumer_type == "consumer":
    row["target_market_b2b_industry"] = None
    row["target_market_b2b_size"] = None
    row["target_market_b2b_age"] = None
  if consumer_type == "b2b":
    row["target_market"] = None
  # Normalize legal entity early so we never write long explanatory strings to the DB.
  # If the client isn't sure, default to Sole proprietor.
  normalized_legal_entity = _normalize_legal_entity(payload.get("legal_entity"))
  row["legal_entity"] = normalized_legal_entity
  if payload.get("legal_entity") is None or not str(payload.get("legal_entity")).strip():
    payload["legal_entity"] = normalized_legal_entity
  # These fields are stored but not collected in the UI right now.
  if row.get("description") is None:
    row["description"] = ""
  if row.get("product_keywords") is None:
    row["product_keywords"] = ""
  # Legacy fields removed from the UI; keep non-null for backward-compatible DB schemas.
  if row.get("customer_age_range") is None:
    row["customer_age_range"] = ""
  if row.get("customer_income_level") is None:
    row["customer_income_level"] = ""
  if row.get("customer_type") is None:
    row["customer_type"] = ""
  if row.get("customer_additional_details") is None:
    row["customer_additional_details"] = ""
  if row.get("pricing_model") is None:
    row["pricing_model"] = ""
  # Legacy field removed from UI; keep non-null for backward-compatible DB schemas.
  if row.get("founder_background") is None:
    row["founder_background"] = ""

  # Operating model (from GPT consultant finalization)
  operating_required = (
    "consumer_type",
    "unit_name",
    "unit_description",
    "units_per_week_capacity",
    "unit_price",
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
  )
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
    geo_cov = str(geographic_coverage).strip()
    # Enforce that geographic_coverage is a concrete area list (ZIPs/counties/metros/states),
    # not a radius like "within 25 miles".
    try:
      import re

      geo_lower = geo_cov.lower()
      if "radius" in geo_lower:
        errors["geographic_coverage"] = (
          "geographic_coverage must be ZIPs, counties, metro areas, and/or states (not a radius)."
        )
      if re.search(r"\bwithin\s+\d+(?:\.\d+)?\s*(?:mi|mile|miles|km|kilometer|kilometers)\b", geo_lower):
        errors["geographic_coverage"] = (
          "geographic_coverage must be ZIPs, counties, metro areas, and/or states (not a radius)."
        )
      if re.search(r"\b\d+(?:\.\d+)?\s*(?:mi|mile|miles|km|kilometer|kilometers)\b", geo_lower):
        errors["geographic_coverage"] = (
          "geographic_coverage must be ZIPs, counties, metro areas, and/or states (not a radius)."
        )
    except Exception:
      pass
    row["geographic_coverage"] = geo_cov

  # Validate numeric capacity
  try:
    row["units_per_week_capacity"] = float(payload.get("units_per_week_capacity"))
  except Exception:
    errors["units_per_week_capacity"] = "units_per_week_capacity must be a number"

  # Validate numeric unit price
  try:
    row["unit_price"] = float(payload.get("unit_price"))
  except Exception:
    errors["unit_price"] = "unit_price must be a number"
  else:
    if row["unit_price"] <= 0:
      errors["unit_price"] = "unit_price must be greater than 0"

  # Store countries/milestones as JSON strings for TEXT columns.
  for key in ("countries", "milestones"):
    val = payload.get(key)
    if isinstance(val, str):
      # Allow already-serialized JSON strings.
      row[key] = val
    else:
      row[key] = json.dumps(val, ensure_ascii=False)

  # Require at least one forward-looking milestone.
  try:
    milestones_val = payload.get("milestones")
    if isinstance(milestones_val, str):
      milestones_val = json.loads(milestones_val)
    if not isinstance(milestones_val, list) or len(milestones_val) == 0:
      errors["milestones"] = "At least one future milestone is required"
    else:
      for idx, m in enumerate(milestones_val):
        if not isinstance(m, dict):
          errors["milestones"] = "milestones must be a list of {description, timing}"
          break
        if not str(m.get("description") or "").strip():
          errors["milestones"] = f"milestones[{idx}].description is required"
          break
        if not str(m.get("timing") or "").strip():
          errors["milestones"] = f"milestones[{idx}].timing is required"
          break
  except Exception:
    errors["milestones"] = "milestones must be valid JSON"

  confidence = payload.get("operating_model_confidence", None)
  if confidence is not None and confidence != "":
    try:
      row["operating_model_confidence"] = float(confidence)
    except Exception:
      errors["operating_model_confidence"] = (
        "operating_model_confidence must be a number"
      )

  if errors:
    raise IntakeValidationError(errors)

  conn = get_mysql_connection()
  try:
    try:
      row["naics_code"] = get_naics_from_business_type(
        conn, str(business_type).strip()
      )
    except Exception as exc:
      raise IntakeValidationError({"business_type": str(exc)}) from exc

    inserted: Optional[Dict[str, Any]] = None
    for _ in range(5):
      try:
        inserted = insert_intake_submission(conn=conn, row=row)
        break
      except Exception as exc:
        msg = str(exc).lower()
        if "duplicate" in msg and "client_id" in msg:
          raise IntakeValidationError(
            {"client_id": "client_id already exists; start a new intake session"}
          ) from exc
        raise

    if not inserted or not inserted.get("inserted_id"):
      raise RuntimeError("Failed to write intake submission.")

    submission_id = int(inserted["inserted_id"])
    submission_row = fetch_intake_submission_by_id(conn=conn, submission_id=submission_id)

    finmo_path = create_client_finmo_workbook(
      template_path=finmo_template_path,
      client_finmo_dir=client_finmo_dir,
      business_name=str(submission_row.get("business_name") or ""),
      created_at=submission_row.get("created_at"),
      client_id=client_id,
    )
    update_intake_submission_finmo_path(
      conn=conn, submission_id=submission_id, finmo_path=finmo_path
    )
    submission_row["finmo_path"] = finmo_path
  finally:
    try:
      conn.close()
    except Exception:
      pass

  revenue_info = sync_intake_revenue_to_finmo(client_id=client_id)
  populated_info = populate_finmo(
    str(business_type).strip(),
    finmo_path=str(submission_row.get("finmo_path") or ""),
  )
  soi_info = write_soi_revenue_total_all_firms_to_finmo(
    client_id=client_id,
    soi_corp_base=str(populated_info.get("soi_corp_base") or "").strip() or None,
  )

  try:
    email_result = send_intake_confirmation_email(
      to_email=str(payload.get("email_address") or "").strip(),
      first_name=str(payload.get("first_name") or "").strip(),
      last_name=str(payload.get("last_name") or "").strip(),
      client_id=client_id,
    )
  except Exception as exc:
    email_result = {"sent": False, "reason": str(exc)}

  return {
    "status": "ok",
    "intake_submission_id": submission_row.get("id"),
    "client_id": client_id,
    "naics_code": row.get("naics_code"),
    "finmo_path": submission_row.get("finmo_path"),
    "starting_revenue_intake": revenue_info.get("starting_revenue_intake"),
    "soi_receipts_per_return": soi_info.get("soi_receipts_per_return"),
    "populated": populated_info,
    "email": email_result,
  }
