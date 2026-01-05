from __future__ import annotations

import os
import secrets
import shutil
import smtplib
import string
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Set, List


# Windows filename-safe special characters (avoid <>:"/\\|?*).
ALLOWED_SPECIALS = "!@#$%^&_-"


def generate_client_id() -> str:
  specials = "".join(secrets.choice(ALLOWED_SPECIALS) for _ in range(2))
  letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(7))
  digits = "".join(secrets.choice(string.digits) for _ in range(11))
  return f"{specials}{letters}{digits}"


def parse_business_start_date(value: Any) -> date:
  if value is None:
    raise ValueError("business_start_date is required")
  raw = str(value).strip()
  if not raw:
    raise ValueError("business_start_date is required")

  for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
    try:
      return datetime.strptime(raw, fmt).date()
    except ValueError:
      continue

  raise ValueError(
    "business_start_date must be YYYY-MM-DD (or MM-DD-YYYY)"
  )


def _mysql_env() -> Tuple[str, int, str, str, str]:
  host = (os.getenv("MYSQL_HOST") or "").strip()
  port_raw = (os.getenv("MYSQL_PORT") or "3306").strip()
  user = (os.getenv("MYSQL_USER") or "").strip()
  password = os.getenv("MYSQL_PASSWORD") or ""
  database = (os.getenv("MYSQL_DB") or "").strip()
  if not host or not user or not database:
    raise RuntimeError("Missing MYSQL_HOST/MYSQL_USER/MYSQL_DB configuration.")
  try:
    port = int(port_raw)
  except ValueError:
    port = 3306
  return host, port, user, password, database


def sanitize_filename_component(value: str, *, max_len: int = 80) -> str:
  cleaned = "".join(ch for ch in value.strip() if ch not in '<>:"/\\|?*')
  cleaned = " ".join(cleaned.split())
  cleaned = cleaned.strip(" .")
  if not cleaned:
    cleaned = "client"
  if len(cleaned) > max_len:
    cleaned = cleaned[:max_len].rstrip(" .")
  return cleaned


def _sanitize_env_path(value: str) -> str:
  # Common when .env values get wrapped in quotes.
  cleaned = str(value).strip()
  if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
    cleaned = cleaned[1:-1].strip()
  if cleaned.startswith("'") and cleaned.endswith("'") and len(cleaned) >= 2:
    cleaned = cleaned[1:-1].strip()
  return cleaned


def created_at_numeric(value: Any) -> str:
  if isinstance(value, datetime):
    return value.strftime("%Y%m%d%H%M%S%f")
  raw = str(value).strip()
  digits = "".join(ch for ch in raw if ch.isdigit())
  if not digits:
    raise ValueError(f"Unable to derive numeric timestamp from created_at={value!r}")
  return digits


def create_client_finmo_workbook(
  *,
  template_path: str,
  client_finmo_dir: str,
  business_name: str,
  created_at: Any,
  client_id: str,
) -> str:
  template = Path(_sanitize_env_path(template_path))
  if not template.exists():
    raise FileNotFoundError(f"FINMO template not found at {template}")

  dest_dir = Path(_sanitize_env_path(client_finmo_dir))
  dest_dir.mkdir(parents=True, exist_ok=True)

  business_part = sanitize_filename_component(business_name)
  ts_part = created_at_numeric(created_at)
  # User requirement: name the copy using business_name + numeric created_at only.
  base_name = f"{business_part}_{ts_part}"
  dest_path = dest_dir / f"{base_name}.xlsx"

  # Avoid collisions without introducing invalid filename characters.
  counter = 2
  while dest_path.exists():
    dest_path = dest_dir / f"{base_name}_{counter}.xlsx"
    counter += 1

  shutil.copy2(str(template), str(dest_path))
  return str(dest_path)


def insert_intake_submission(
  *,
  conn,
  row: Dict[str, Any],
) -> Dict[str, Any]:
  import json

  def _table_column_meta(conn, table_name: str) -> Dict[str, Dict[str, Any]]:
    cur = conn.cursor()
    try:
      cur.execute(
        """
        SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
      )
      rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
    meta: Dict[str, Dict[str, Any]] = {}
    for r in rows:
      try:
        name = str(r[0])
      except Exception:
        continue
      is_nullable = str(r[1] or "").strip().upper() == "YES" if len(r) > 1 else True
      default_val = r[2] if len(r) > 2 else None
      meta[name] = {"nullable": bool(is_nullable), "default": default_val}
    return meta

  column_meta = _table_column_meta(conn, "intake_submissions")
  available_columns: Set[str] = set(column_meta.keys())

  # Candidate columns this app knows how to provide. We insert only columns that exist.
  candidate_columns: List[str] = [
    "client_id",
    "consumer_type",
    "business_name",
    "legal_entity",
    "business_type",
    "naics_code",
    # Legacy field; safe if present, ignored if dropped.
    "description",
    "business_description_summary",
    "key_people_summary",
    "target_market",
    "target_market_summary",
    "target_market_b2b_industry",
    "target_market_b2b_size",
    "target_market_b2b_age",
    "address",
    "product_keywords",
    "customer_age_range",
    "customer_income_level",
    "customer_type",
    "customer_additional_details",
    "first_name",
    "last_name",
    "email_address",
    "phone_number",
    "how_did_you_hear",
    "pricing_model",
    "founder_background",
    "business_start_date",
    "current_revenue",
    "starting_revenue",
    "current_cogs",
    "other_operating_expense",
    "monthly_rent_expense",
    "other_monthly_debt_payments",
    "current_payroll",
    "current_num_employees",
    "current_capex",
    "ar_balance",
    "ap_balance",
    "inventory_balance",
    "total_debt_outstanding",
    "annual_interest_payment",
    "annual_principal_payment",
    "owner_compensation",
    "cash_on_hand",
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
    "initial_assets",
    "initial_lease",
    "initial_equity",
    "operating_model_confidence",
    "ops_concept_model_json",
    "fulfillment_model_json",
    "marketing_model_json",
    "pricing_model_json",
    "revenue_model_json",
    "headcount_model_json",
    "milestones_model_json",
    "driver_events_json",
    "driver_revision_nonce",
    "year1_revenue",
    "year1_marketing_spend",
    "year1_payroll",
  ]

  required_in_db = {
    "client_id",
    "consumer_type",
    "business_name",
    "business_type",
    "naics_code",
    "first_name",
    "last_name",
    "email_address",
    "business_start_date",
    "current_revenue",
    "starting_revenue",
    "legal_entity",
    "business_description_summary",
    "key_people_summary",
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
    "target_market",
    "target_market_summary",
    "target_market_b2b_industry",
    "target_market_b2b_size",
    "target_market_b2b_age",
  }

  missing_required = sorted([c for c in required_in_db if c not in available_columns])
  if missing_required:
    raise RuntimeError(
      "intake_submissions is missing required columns: "
      + ", ".join(missing_required)
    )

  # unit_price is optional for multi-stream / multi-output businesses; when not applicable,
  # it is stored as NULL. Ensure the DB schema permits that so we never silently fall back
  # to a misleading default like 0.
  if row.get("unit_price") is None and "unit_price" in available_columns:
    meta = column_meta.get("unit_price") or {}
    if meta and not bool(meta.get("nullable")):
      raise RuntimeError(
        "intake_submissions.unit_price must be NULLable to support multi-stream businesses. "
        "Run: ALTER TABLE intake_submissions MODIFY unit_price DOUBLE NULL;"
      )

  columns: List[str] = [c for c in candidate_columns if c in available_columns]
  values: List[Any] = []
  for col in columns:
    val = row.get(col)
    if isinstance(val, (dict, list)):
      val = json.dumps(val, ensure_ascii=False)
    values.append(val)
  placeholders = ",".join(["%s"] * len(columns))
  cols_sql = ",".join(f"`{c}`" for c in columns)
  sql = f"INSERT INTO `intake_submissions` ({cols_sql}) VALUES ({placeholders})"

  cur = conn.cursor()
  try:
    cur.execute(sql, values)
    conn.commit()
    inserted_id = getattr(cur, "lastrowid", None)
    return {"inserted_id": inserted_id, "client_id": row.get("client_id")}
  finally:
    try:
      cur.close()
    except Exception:
      pass


def fetch_intake_submission_by_id(
  *,
  conn,
  submission_id: int,
) -> Dict[str, Any]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT * FROM intake_submissions WHERE id = %s LIMIT 1",
      (submission_id,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass

  if not row:
    raise RuntimeError(f"intake_submissions row not found for id={submission_id}")
  if not isinstance(row, dict):
    raise RuntimeError("Unexpected DB row shape for intake_submissions.")
  return row


def fetch_intake_submission_by_client_id(
  *,
  conn,
  client_id: str,
) -> Dict[str, Any]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT * FROM intake_submissions WHERE client_id = %s LIMIT 1",
      (str(client_id).strip(),),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass

  if not row:
    raise RuntimeError(
      f"intake_submissions row not found for client_id={client_id!r}"
    )
  if not isinstance(row, dict):
    raise RuntimeError("Unexpected DB row shape for intake_submissions.")
  return row


def update_intake_submission_finmo_path(
  *,
  conn,
  submission_id: int,
  finmo_path: str,
) -> None:
  cur = conn.cursor()
  try:
    cur.execute(
      "UPDATE intake_submissions SET finmo_path = %s WHERE id = %s",
      (finmo_path, submission_id),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def update_intake_operating_model_fields(
  *,
  conn,
  client_id: str,
  updates: Dict[str, Any],
) -> None:
  allowed = {
    "unit_name",
    "unit_description",
    "units_per_week_capacity",
    "sales_modality",
    "geographic_scope",
    "geographic_coverage",
    "countries",
    "milestones",
    "capacity_driver",
    "primary_growth_lever",
    "operating_model_confidence",
  }

  set_parts = []
  values = []
  for key, val in updates.items():
    if key not in allowed:
      continue
    if val is None:
      continue
    if key in ("countries", "milestones") and not isinstance(val, str):
      # Store arrays as JSON strings in TEXT columns.
      import json

      val = json.dumps(val, ensure_ascii=False)
    set_parts.append(f"`{key}` = %s")
    values.append(val)

  if not set_parts:
    return

  values.append(str(client_id).strip())
  sql = "UPDATE intake_submissions SET " + ", ".join(set_parts) + " WHERE client_id = %s"
  cur = conn.cursor()
  try:
    cur.execute(sql, values)
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def get_mysql_connection():
  try:
    import mysql.connector  # type: ignore
  except Exception as exc:
    raise RuntimeError(
      "mysql-connector-python is not installed."
    ) from exc

  host, port, user, password, database = _mysql_env()
  return mysql.connector.connect(
    host=host,
    port=port,
    user=user,
    password=password,
    database=database,
  )


def send_intake_confirmation_email(
  *,
  to_email: str,
  first_name: str,
  last_name: str,
  client_id: str,
) -> Dict[str, Any]:
  email_host = (os.getenv("EMAIL_HOST") or "").strip()
  email_port = (os.getenv("EMAIL_PORT") or "587").strip()
  email_user = (os.getenv("EMAIL_USER") or "").strip()
  email_password = os.getenv("EMAIL_PASSWORD") or ""

  if not email_host or not email_user or not email_password:
    return {"sent": False, "reason": "email_not_configured"}

  try:
    port = int(email_port)
  except ValueError:
    port = 587

  msg = EmailMessage()
  msg["Subject"] = "We received your business plan intake"
  msg["From"] = email_user
  msg["To"] = to_email

  body = f"""Dear {first_name} {last_name},

Thank you for submitting your business plan intake. We've received your information and will begin reviewing it shortly.

Your reference code is: {client_id}

Please keep this code for your records-our team may use it to quickly locate your submission if you contact us with questions or updates.

Sincerely,
Tithe Financial Wealth Management
"""
  msg.set_content(body)

  with smtplib.SMTP(email_host, port, timeout=30) as smtp:
    smtp.starttls()
    smtp.login(email_user, email_password)
    smtp.send_message(msg)

  return {"sent": True}
