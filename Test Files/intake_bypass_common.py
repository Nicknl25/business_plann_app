"""Shared helpers for the intake-bypass tooling.

The intake-bypass runner lets the user exercise the *post-intake* pipeline
without re-running the GPT intake conversation. It does this with the
"baseline + overrides" model:

  - A baseline snapshot is the structured intake output (operating_model_json,
    target_market_json, people_json, financials_json, ...) captured once from a
    real, intake-complete draft. Post-intake consumes these structured JSON
    payloads -- it never consumes raw intake answers -- so reusing a real
    baseline guarantees the JSON is shaped exactly the way post-intake expects.

  - Overrides are scalar values (cash_on_hand, current_capex, payroll, price,
    naics, ...) the user edits per scenario. The runner applies them onto a
    copy of the baseline before writing the fresh draft, so the user can author
    stress scenarios (e.g. "airline with $0 capex") by changing numbers only.

This module holds the pieces both ``capture_intake_baseline.py`` and
``run_intake_bypass.py`` need: env/DB access, JSON helpers, and the
override -> JSON-path mapping.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
DEFAULT_BASELINES_DIR = THIS_DIR / "intake_bypass_baselines"
DEFAULT_SCENARIOS_XLSX = THIS_DIR / "intake_bypass_scenarios.xlsx"

# Columns copied from the baseline draft into a fresh draft. This mirrors the
# proven clone in run_persisted_system_run.py:_clone_source_into_target_draft.
# Each entry is (sql_column, snapshot_key, is_json).
BASELINE_FLAT_COLUMNS: List[Tuple[str, str]] = [
  ("business_name", "business_name"),
  ("business_address", "business_address"),
  ("address_street", "address_street"),
  ("address_city", "address_city"),
  ("address_state", "address_state"),
  ("address_zip", "address_zip"),
  ("address_country", "address_country"),
  ("business_start_date", "business_start_date"),
]

BASELINE_JSON_COLUMNS: List[str] = [
  "messages_json",
  "operating_model_json",
  "target_market_json",
  "people_json",
  "financials_json",
  "marketing_model_json",
  "financials_year1_json",
  "realism_memo_json",
  "pending_ops_milestone_json",
  "fulfillment_json",
]


# ---------------------------------------------------------------------------
# Environment / DB
# ---------------------------------------------------------------------------
def load_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  env_path = ROOT / ".env"
  try:
    if env_path.exists():
      load_dotenv(env_path, override=False)
    else:
      load_dotenv(override=False)
  except Exception:
    pass


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def mysql_connect():
  import mysql.connector  # type: ignore

  host = _string(os.getenv("MYSQL_HOST"))
  user = _string(os.getenv("MYSQL_USER"))
  password = str(os.getenv("MYSQL_PASSWORD") or "")
  database = _string(os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME"))
  port_raw = _string(os.getenv("MYSQL_PORT") or "3306")
  if not (host and user and database):
    raise RuntimeError("MYSQL_HOST, MYSQL_USER, and MYSQL_DB must be configured in .env.")
  try:
    port = int(port_raw or "3306")
  except Exception:
    port = 3306
  return mysql.connector.connect(host=host, user=user, password=password, database=database, port=port)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def parse_json(value: Any) -> Any:
  """Parse a DB JSON column (string) into a Python object, pass dicts through."""
  if value is None:
    return None
  if isinstance(value, (dict, list)):
    return value
  if isinstance(value, (bytes, bytearray)):
    value = value.decode("utf-8", "replace")
  text = str(value).strip()
  if not text:
    return None
  try:
    return json.loads(text)
  except Exception:
    return value


def sql_json_value(value: Any) -> Any:
  """Serialize dicts/lists for a MySQL JSON/LONGTEXT column; pass scalars through."""
  if isinstance(value, (dict, list)):
    return json.dumps(value, ensure_ascii=False)
  return value


# ---------------------------------------------------------------------------
# Override registry
# ---------------------------------------------------------------------------
# "Numbers only" scalars that live exactly once, inside financials_json. These
# are the safest, highest-value overrides for stress scenarios: the post-intake
# solver reads them directly as opening balances / Year-1 totals.
FINANCIALS_SCALAR_FIELDS: List[str] = [
  "cash_on_hand",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "current_capex",
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "other_monthly_debt_payments",
  "monthly_rent_expense",
  "other_operating_expense",
  "owner_compensation",
  "current_payroll",
  "payroll_total_year1",
  "current_num_employees",
  "current_cogs",
  "current_revenue",
]

# Percent fields in financials_json: accept "29%" or 0.29 or 29 -> normalized to fraction.
FINANCIALS_PERCENT_FIELDS: List[str] = [
  "cogs_percent_of_revenue",
]

# Integer-valued financials fields.
FINANCIALS_INT_FIELDS = {"current_num_employees"}

# Fields denormalized across operating_model_json (top level + every
# lob_models[*].products[*]) and financials_year1_json lobs[*].products[*].
# The post-intake mapping re-derives revenue from these, so overriding them is
# supported but flagged in the README as "shape-affecting".
PRODUCT_NUMERIC_FIELDS: List[str] = [
  "unit_price",
  "units_per_week_capacity",
  "utilization_rate",
]

# operating_model_json top-level descriptors.
OPS_DESCRIPTOR_FIELDS = {
  "naics": "business_naics_6",
  "business_naics_6": "business_naics_6",
  "business_stage": "business_stage",
}

# Flat draft columns that may be overridden directly.
FLAT_OVERRIDE_FIELDS = {
  "business_name",
  "business_start_date",
  "business_address",
  "address_street",
  "address_city",
  "address_state",
  "address_zip",
  "address_country",
}

# Fields that are control/meta and must never be treated as overrides.
RESERVED_FIELDS = {"baseline", "scenario_notes", "scenario_name"}


def coerce_number(raw: Any, *, percent: bool = False, integer: bool = False) -> Optional[float]:
  """Parse a spreadsheet cell into a number. Accepts $1,234.50, 29%, plain ints."""
  if raw is None:
    return None
  if isinstance(raw, bool):
    raise ValueError(f"expected a number, got boolean {raw!r}")
  if isinstance(raw, (int, float)):
    val = float(raw)
  else:
    text = str(raw).strip()
    if not text:
      return None
    had_percent = text.endswith("%")
    cleaned = text.replace("$", "").replace(",", "").replace("%", "").strip()
    if cleaned == "":
      return None
    try:
      val = float(cleaned)
    except Exception as exc:
      raise ValueError(f"could not parse number from {raw!r}: {exc}") from exc
    if percent and (had_percent or val > 1.0):
      val = val / 100.0
      return val
  if percent and val > 1.0:
    val = val / 100.0
  if integer:
    return float(int(round(val)))
  return val


def _set_product_field(structured: Dict[str, Any], field: str, value: float, audit: List[Dict[str, Any]]) -> None:
  om = structured.get("operating_model_json")
  if isinstance(om, dict):
    if field in om:
      audit.append({"field": field, "path": f"operating_model_json.{field}", "value": value})
    om[field] = value
    for lob in (om.get("lob_models") or []):
      for product in (lob.get("products") or []) if isinstance(lob, dict) else []:
        if isinstance(product, dict):
          product[field] = value
  fy1 = structured.get("financials_year1_json")
  if isinstance(fy1, dict):
    for lob in (fy1.get("lobs") or []):
      for product in (lob.get("products") or []) if isinstance(lob, dict) else []:
        if isinstance(product, dict) and field in product:
          product[field] = value


def apply_overrides(
  *,
  flat: Dict[str, Any],
  structured: Dict[str, Any],
  overrides: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """Mutate ``flat`` and ``structured`` in place per ``overrides``.

  Returns an audit list (one entry per applied override) for reporting. Raises
  ValueError on an unknown field so a typo in the spreadsheet fails loud rather
  than silently doing nothing.
  """
  audit: List[Dict[str, Any]] = []
  financials = structured.get("financials_json")
  if not isinstance(financials, dict):
    financials = {}
    structured["financials_json"] = financials

  for key, raw in overrides.items():
    field = _string(key)
    if not field or field.startswith("#") or field in RESERVED_FIELDS:
      continue
    # Treat blank cells as "inherit baseline".
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
      continue

    if field in FLAT_OVERRIDE_FIELDS:
      flat[field] = _string(raw)
      audit.append({"field": field, "path": f"draft.{field}", "value": flat[field]})
      continue

    if field in FINANCIALS_PERCENT_FIELDS:
      val = coerce_number(raw, percent=True)
      if val is None:
        continue
      financials[field] = val
      audit.append({"field": field, "path": f"financials_json.{field}", "value": val})
      continue

    if field in FINANCIALS_SCALAR_FIELDS:
      val = coerce_number(raw, integer=(field in FINANCIALS_INT_FIELDS))
      if val is None:
        continue
      if field in FINANCIALS_INT_FIELDS:
        financials[field] = int(val)
      else:
        financials[field] = val
      audit.append({"field": field, "path": f"financials_json.{field}", "value": financials[field]})
      continue

    if field in PRODUCT_NUMERIC_FIELDS:
      val = coerce_number(raw, percent=(field == "utilization_rate"))
      if val is None:
        continue
      _set_product_field(structured, field, val, audit)
      audit.append({"field": field, "path": f"operating_model_json+financials_year1_json.{field}", "value": val})
      continue

    if field in OPS_DESCRIPTOR_FIELDS:
      om = structured.get("operating_model_json")
      if not isinstance(om, dict):
        om = {}
        structured["operating_model_json"] = om
      target = OPS_DESCRIPTOR_FIELDS[field]
      om[target] = _string(raw)
      audit.append({"field": field, "path": f"operating_model_json.{target}", "value": om[target]})
      continue

    raise ValueError(
      f"Unknown override field {field!r}. Supported: "
      f"{sorted(set(FLAT_OVERRIDE_FIELDS) | set(FINANCIALS_SCALAR_FIELDS) | set(FINANCIALS_PERCENT_FIELDS) | set(PRODUCT_NUMERIC_FIELDS) | set(OPS_DESCRIPTOR_FIELDS))}"
    )

  return audit


def load_baseline(baselines_dir: Path, name: str) -> Dict[str, Any]:
  name = _string(name)
  if not name:
    raise RuntimeError("Scenario is missing a 'baseline' value.")
  if name.endswith(".json"):
    name = name[: -len(".json")]
  path = baselines_dir / f"{name}.json"
  if not path.exists():
    available = sorted(p.stem for p in baselines_dir.glob("*.json")) if baselines_dir.exists() else []
    raise RuntimeError(f"Baseline {name!r} not found at {path}. Available: {available}")
  with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
  if not isinstance(data, dict) or "structured" not in data:
    raise RuntimeError(f"Baseline file {path} is malformed (missing 'structured').")
  return data
