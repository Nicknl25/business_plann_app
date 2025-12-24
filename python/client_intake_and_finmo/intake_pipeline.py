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


def process_intake_submission(payload: Dict[str, Any]) -> Dict[str, Any]:
  errors: Dict[str, str] = {}

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
    "description",
    "product_keywords",
    "selling_method",
    "customer_age_range",
    "customer_income_level",
    "customer_type",
    "first_name",
    "last_name",
    "email_address",
    "pricing_model",
    "founder_background",
    "business_start_date",
  )
  for key in required_text_fields:
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
  row["business_start_date"] = business_start_date
  row["current_revenue"] = revenue_value

  # Operating model (from GPT consultant finalization)
  operating_required = (
    "unit_name",
    "unit_description",
    "units_per_week_capacity",
    "sales_modality",
    "geographic_scope",
    "countries",
    "milestones",
    "capacity_driver",
    "primary_growth_lever",
  )
  for key in operating_required:
    if payload.get(key) is None or payload.get(key) == "":
      errors[key] = f"{key} is required"

  # Validate numeric capacity
  try:
    row["units_per_week_capacity"] = float(payload.get("units_per_week_capacity"))
  except Exception:
    errors["units_per_week_capacity"] = "units_per_week_capacity must be a number"

  # Store countries/milestones as JSON strings for TEXT columns.
  for key in ("countries", "milestones"):
    val = payload.get(key)
    if isinstance(val, str):
      # Allow already-serialized JSON strings.
      row[key] = val
    else:
      row[key] = json.dumps(val, ensure_ascii=False)

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
      raise RuntimeError("Failed to insert intake submission.")

    submission_id = int(inserted["inserted_id"])
    submission_row = fetch_intake_submission_by_id(
      conn=conn, submission_id=submission_id
    )

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
