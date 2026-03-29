import argparse
import json
import os
import re
import sys
import textwrap
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

try:
  import mysql.connector  # type: ignore
except Exception:
  mysql = None  # type: ignore

try:
  from dotenv import load_dotenv
except Exception:
  load_dotenv = None


OPENAI_URL = "https://api.openai.com/v1/responses"
_FACT_PATTERN = re.compile(r"\{\{fact:([A-Za-z0-9_.-]+)\}\}")
US_EASTERN = ZoneInfo("America/New_York")
DEFAULT_TEST_RUNS_DIR = r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Test Runs"
DEFAULT_TEST_RUNS_DATA_DIR = r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Test Runs Data"
DEFAULT_TERMINAL_LOGS_DIR = r"C:\Users\ignat\OneDrive - Tithe Financial Wealth Management\Apps\Terminal Logs"

BUSINESS_FACT_FIELDS = {"name", "address", "start_date"}
OPS_FACT_FIELDS = {
  "consumer_type",
  "business_type",
  "unit_name",
  "unit_description",
  "unit_cadence",
  "units_per_week_capacity",
  "units_per_period_capacity",
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
  "total_debt_outstanding",
  "legal_entity",
  "confidence",
  "business_description_summary",
}
MARKET_FACT_FIELDS = {
  "consumer_type",
  "gender_age_intent",
  "income_intent",
  "selections",
  "b2b_industry_terms",
  "b2b_naics_6",
  "b2b_size_bands",
  "b2b_age_bands",
  "target_market_summary",
  "confidence",
}
PEOPLE_FACT_FIELDS = {"people", "key_people_summary", "confidence"}
FINANCIALS_FACT_FIELDS = {
  "financials_summary",
  "current_revenue",
  "current_cogs",
  "marketing_total_year1",
  "marketing_percent_of_revenue",
  "other_operating_expense",
  "monthly_rent_expense",
  "other_monthly_debt_payments",
  "current_payroll",
  "current_num_employees",
  "current_capex",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "owner_compensation",
  "cash_on_hand",
  "confidence",
}
FACT_GROUPS = {
  "business": BUSINESS_FACT_FIELDS,
  "ops": OPS_FACT_FIELDS,
  "market": MARKET_FACT_FIELDS,
  "people": PEOPLE_FACT_FIELDS,
  "financials": FINANCIALS_FACT_FIELDS,
}
OPS_MONEY_FIELDS = {"unit_price", "initial_assets", "initial_equity", "total_debt_outstanding"}
FIN_MONEY_FIELDS = {
  "current_revenue",
  "current_cogs",
  "marketing_total_year1",
  "other_operating_expense",
  "monthly_rent_expense",
  "other_monthly_debt_payments",
  "current_payroll",
  "current_capex",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "initial_assets",
  "initial_equity",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "owner_compensation",
  "cash_on_hand",
}
FIN_PERCENT_FIELDS = {
  "marketing_percent_of_revenue",
}
COUNT_FIELDS = {"units_per_week_capacity", "units_per_period_capacity", "current_num_employees"}


def _load_env() -> None:
  if load_dotenv:
    try:
      repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
      root_env = os.path.join(repo_root, ".env")
      if os.path.exists(root_env):
        load_dotenv(root_env, override=False)
      else:
        load_dotenv(override=False)
    except Exception:
      pass


def _mysql_env() -> Optional[Dict[str, Any]]:
  host = os.getenv("MYSQL_HOST", "").strip()
  user = os.getenv("MYSQL_USER", "").strip()
  password = os.getenv("MYSQL_PASSWORD", "")
  database = os.getenv("MYSQL_DB", "").strip()
  port_raw = os.getenv("MYSQL_PORT", "3306").strip()
  if not (host and user and database):
    return None
  try:
    port = int(port_raw or "3306")
  except Exception:
    port = 3306
  return {
    "host": host,
    "user": user,
    "password": password,
    "database": database,
    "port": port,
  }


class _SimulatorMetricsStore:
  def __init__(self) -> None:
    self._conn = None
    self._enabled = False
    if mysql is None or getattr(mysql, "connector", None) is None:
      return
    cfg = _mysql_env()
    if not cfg:
      return
    try:
      self._conn = mysql.connector.connect(**cfg)
      self._ensure_tables()
      self._enabled = True
    except Exception:
      self._conn = None
      self._enabled = False

  @property
  def enabled(self) -> bool:
    return self._enabled and self._conn is not None

  def close(self) -> None:
    if self._conn is not None:
      try:
        self._conn.close()
      except Exception:
        pass
    self._conn = None
    self._enabled = False

  def _ensure_tables(self) -> None:
    if self._conn is None:
      return
    cur = self._conn.cursor()
    try:
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intake_sim_runs (
          run_id VARCHAR(32) PRIMARY KEY,
          seed TEXT NOT NULL,
          model_name VARCHAR(128) NOT NULL,
          base_url VARCHAR(255) NOT NULL,
          output_dir TEXT NULL,
          started_at DATETIME(6) NOT NULL,
          ended_at DATETIME(6) NULL,
          total_duration_ms BIGINT NULL,
          start_hour_local TINYINT NULL,
          status VARCHAR(32) NOT NULL,
          stop_reason TEXT NULL,
          draft_id VARCHAR(64) NULL,
          client_id VARCHAR(64) NULL,
          business_name VARCHAR(255) NULL,
          business_start_date VARCHAR(32) NULL,
          business_address TEXT NULL,
          session_create_ms BIGINT NULL,
          initial_app_response_ms BIGINT NULL,
          total_turns INT NOT NULL DEFAULT 0,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS intake_sim_turn_metrics (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          run_id VARCHAR(32) NOT NULL,
          turn_index INT NOT NULL,
          focus VARCHAR(32) NULL,
          turn_started_at DATETIME(6) NOT NULL,
          draft_fetch_ms BIGINT NULL,
          client_answer_ms BIGINT NULL,
          app_response_ms BIGINT NULL,
          assistant_chars INT NULL,
          user_chars INT NULL,
          stop_flag TINYINT(1) NOT NULL DEFAULT 0,
          stop_reason TEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          INDEX idx_intake_sim_turn_metrics_run_turn (run_id, turn_index)
        )
        """
      )
      self._conn.commit()
    finally:
      cur.close()

  def create_run(
    self,
    *,
    run_id: str,
    seed: str,
    model_name: str,
    base_url: str,
    output_dir: str,
    started_at: datetime,
  ) -> None:
    if not self.enabled:
      return
    cur = self._conn.cursor()
    try:
      cur.execute(
        """
        INSERT INTO intake_sim_runs (
          run_id, seed, model_name, base_url, output_dir, started_at, start_hour_local, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
          run_id,
          seed,
          model_name,
          base_url,
          output_dir,
          started_at,
          started_at.hour,
          "running",
        ),
      )
      self._conn.commit()
    finally:
      cur.close()

  def update_run_bootstrap(
    self,
    *,
    run_id: str,
    business_name: str,
    business_start_date: str,
    business_address: str,
  ) -> None:
    if not self.enabled:
      return
    cur = self._conn.cursor()
    try:
      cur.execute(
        """
        UPDATE intake_sim_runs
        SET business_name=%s, business_start_date=%s, business_address=%s
        WHERE run_id=%s
        """,
        (business_name, business_start_date, business_address, run_id),
      )
      self._conn.commit()
    finally:
      cur.close()

  def update_run_session(
    self,
    *,
    run_id: str,
    draft_id: Optional[str],
    client_id: Optional[str],
    session_create_ms: Optional[int],
    initial_app_response_ms: Optional[int],
  ) -> None:
    if not self.enabled:
      return
    cur = self._conn.cursor()
    try:
      cur.execute(
        """
        UPDATE intake_sim_runs
        SET draft_id=%s, client_id=%s, session_create_ms=%s, initial_app_response_ms=%s
        WHERE run_id=%s
        """,
        (draft_id, client_id, session_create_ms, initial_app_response_ms, run_id),
      )
      self._conn.commit()
    finally:
      cur.close()

  def insert_turn(
    self,
    *,
    run_id: str,
    turn_index: int,
    focus: str,
    turn_started_at: datetime,
    draft_fetch_ms: Optional[int],
    client_answer_ms: Optional[int],
    app_response_ms: Optional[int],
    assistant_chars: int,
    user_chars: int,
    stop_flag: bool,
    stop_reason: str,
  ) -> None:
    if not self.enabled:
      return
    cur = self._conn.cursor()
    try:
      cur.execute(
        """
        INSERT INTO intake_sim_turn_metrics (
          run_id, turn_index, focus, turn_started_at, draft_fetch_ms, client_answer_ms,
          app_response_ms, assistant_chars, user_chars, stop_flag, stop_reason
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
          run_id,
          turn_index,
          focus,
          turn_started_at,
          draft_fetch_ms,
          client_answer_ms,
          app_response_ms,
          assistant_chars,
          user_chars,
          1 if stop_flag else 0,
          stop_reason or None,
        ),
      )
      self._conn.commit()
    finally:
      cur.close()

  def finish_run(
    self,
    *,
    run_id: str,
    ended_at: datetime,
    total_duration_ms: int,
    total_turns: int,
    status: str,
    stop_reason: str,
  ) -> None:
    if not self.enabled:
      return
    cur = self._conn.cursor()
    try:
      cur.execute(
        """
        UPDATE intake_sim_runs
        SET ended_at=%s, total_duration_ms=%s, total_turns=%s, status=%s, stop_reason=%s
        WHERE run_id=%s
        """,
        (
          ended_at,
          total_duration_ms,
          total_turns,
          status,
          stop_reason,
          run_id,
        ),
      )
      self._conn.commit()
    finally:
      cur.close()


def _post_json(
  url: str,
  payload: Dict[str, Any],
  *,
  timeout: int = 240,
  headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
  resp = requests.post(url, json=payload, timeout=timeout, headers=headers)
  try:
    data = resp.json()
  except Exception:
    data = {"raw": resp.text}
  if resp.status_code >= 400:
    raise RuntimeError(f"POST {url} -> {resp.status_code}: {data}")
  if not isinstance(data, dict):
    raise RuntimeError(f"POST {url} returned non-object payload: {data}")
  return data


def _get_json(url: str, params: Dict[str, Any], *, timeout: int = 240) -> Dict[str, Any]:
  resp = requests.get(url, params=params, timeout=timeout)
  try:
    data = resp.json()
  except Exception:
    data = {"raw": resp.text}
  if resp.status_code >= 400:
    raise RuntimeError(f"GET {url} -> {resp.status_code}: {data}")
  if not isinstance(data, dict):
    raise RuntimeError(f"GET {url} returned non-object payload: {data}")
  return data


def _normalize(text: str) -> str:
  return " ".join(str(text or "").strip().lower().split())


def _parse_json_dict(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  if isinstance(value, (int, float)):
    return float(value)
  try:
    return float(str(value).strip().replace(",", ""))
  except Exception:
    return None


def _format_currency(value: Any) -> str:
  num = _safe_float(value)
  if num is None:
    return "$0"
  if abs(num - round(num)) < 1e-9:
    core = f"{int(round(num)):,}"
  else:
    core = f"{num:,.2f}".rstrip("0").rstrip(".")
  return f"${core}"


def _format_percent(value: Any) -> str:
  num = _safe_float(value)
  if num is None:
    return "0%"
  return f"{num * 100:,.0f}%"


def _format_number(value: Any, *, money: bool) -> str:
  num = _safe_float(value)
  if num is None:
    return "$0" if money else "0"
  if money:
    return _format_currency(num)
  if abs(num - round(num)) < 1e-9:
    return f"{int(round(num)):,}"
  return f"{num:,.2f}".rstrip("0").rstrip(".")


def _format_lease(value: Any) -> str:
  if value is None:
    return "none"
  raw = str(value).strip()
  if not raw:
    return "none"
  parts = [p.strip() for p in raw.split(",")]
  amount = _safe_float(parts[0]) if parts else None
  period = parts[1] if len(parts) > 1 else ""
  if not amount or amount <= 1e-9:
    return "none" if period.lower() in ("none", "n/a", "na", "") else f"$0/{period}"
  money = _format_number(amount, money=True)
  if not period or period.lower() == "none":
    return money
  return f"{money}/{period}"


def _is_allowed_fact_key(key: str) -> bool:
  raw = str(key or "").strip()
  if not raw or raw.count(".") != 1:
    return False
  group, field = raw.split(".", 1)
  allowed = FACT_GROUPS.get(group)
  return bool(allowed and field in allowed)


def _render_fact_placeholders(text: str, draft: Optional[Dict[str, Any]]) -> str:
  if not text or "{{fact:" not in str(text):
    return str(text or "")
  draft = draft or {}
  business_facts = {
    "name": str(draft.get("business_name") or "").strip(),
    "address": str(draft.get("address") or "").strip(),
    "start_date": str(draft.get("business_start_date") or "").strip(),
  }
  shared_context = {
    "operating_model": _parse_json_dict(draft.get("operating_model_json")),
    "target_market": _parse_json_dict(draft.get("target_market_json")),
    "people_capability": _parse_json_dict(draft.get("people_json")),
    "financials": _parse_json_dict(draft.get("financials_json")),
  }

  def resolve_value(group: str, field: str) -> Any:
    if group == "business":
      return business_facts.get(field)
    if group == "ops":
      return (shared_context.get("operating_model") or {}).get(field)
    if group == "market":
      return (shared_context.get("target_market") or {}).get(field)
    if group == "people":
      return (shared_context.get("people_capability") or {}).get(field)
    if group == "financials":
      return (shared_context.get("financials") or {}).get(field)
    return None

  def format_value(group: str, field: str, value: Any) -> str:
    if field == "initial_lease":
      return _format_lease(value)
    if field in COUNT_FIELDS:
      return _format_number(value, money=False)
    if group == "ops" and field in OPS_MONEY_FIELDS:
      return _format_number(value, money=True)
    if group == "financials" and field in FIN_MONEY_FIELDS:
      return _format_number(value, money=True)
    if group == "financials" and field in FIN_PERCENT_FIELDS:
      return _format_percent(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
      return _format_number(value, money=False)
    if isinstance(value, list):
      return ", ".join([str(v) for v in value if v is not None]).strip()
    if isinstance(value, dict):
      return ""
    return str(value).strip() if value is not None else ""

  def _replace(match: re.Match[str]) -> str:
    key = (match.group(1) or "").strip()
    if not _is_allowed_fact_key(key):
      return ""
    group, field = key.split(".", 1)
    return format_value(group, field, resolve_value(group, field))

  return _FACT_PATTERN.sub(_replace, str(text))


def _similarity(a: str, b: str) -> float:
  return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _parse_responses_json(data: Dict[str, Any]) -> Dict[str, Any]:
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
  texts: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text":
        text = part.get("text")
        if isinstance(text, str) and text.strip():
          texts.append(text)
  raw = "\n".join(texts).strip()
  if not raw:
    raise RuntimeError(f"OpenAI response did not contain output_json/output_text: {data}")
  parsed = json.loads(raw)
  if not isinstance(parsed, dict):
    raise RuntimeError(f"OpenAI response was not a JSON object: {parsed}")
  return parsed


def _openai_call(
  *,
  api_key: str,
  model: str,
  schema_name: str,
  schema: Dict[str, Any],
  messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  payload = {
    "model": model,
    "input": messages,
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema_name,
        "schema": schema,
        "strict": True,
      }
    },
  }
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = requests.post(OPENAI_URL, headers=headers, json=payload, timeout=240)
  try:
    data = resp.json()
  except Exception:
    data = {"raw": resp.text}
  if resp.status_code >= 400:
    raise RuntimeError(f"OpenAI -> {resp.status_code}: {data}")
  if not isinstance(data, dict):
    raise RuntimeError(f"OpenAI returned non-object payload: {data}")
  return _parse_responses_json(data)


@dataclass
class Bootstrap:
  business_name: str
  business_start_date: str
  address: str
  address_street: str
  address_city: str
  address_state: str
  address_zip: str
  address_country: str
  private_state: str


class ClientAgent:
  def __init__(self, *, api_key: str, model: str, seed: str, business_start_date_override: Optional[str] = None) -> None:
    self.api_key = api_key
    self.model = model
    self.seed = seed.strip()
    self.business_start_date_override = str(business_start_date_override or "").strip()
    self.private_state = ""

  def bootstrap(self) -> Bootstrap:
    schema = {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "business_name": {"type": "string"},
        "business_start_date": {"type": "string"},
        "address": {"type": "string"},
        "address_street": {"type": "string"},
        "address_city": {"type": "string"},
        "address_state": {"type": "string"},
        "address_zip": {"type": "string"},
        "address_country": {"type": "string"},
        "private_state": {"type": "string"},
      },
      "required": [
        "business_name",
        "business_start_date",
        "address",
        "address_street",
        "address_city",
        "address_state",
        "address_zip",
        "address_country",
        "private_state",
      ],
    }
    system = textwrap.dedent(
      """
      You are preparing a hidden business-owner persona for a black-box intake simulation.

      The seed sentence tells you what kind of business to simulate. Expand it into one coherent,
      plausible business in the United States. Keep it realistic. Do not invent something absurd.

      Return ONLY JSON that matches the schema.
      business_start_date must be formatted MM/DD/YYYY.
      address must be a plausible complete U.S. mailing address.
      private_state must be a compact hidden briefing that captures the business facts, owner style,
      and any important numbers so later answers stay consistent.
      """
    ).strip()
    user = f"Seed business to simulate: {self.seed}"
    if self.business_start_date_override:
      user = (
        f"{user}\n"
        f"Use this exact business_start_date: {self.business_start_date_override}\n"
        "Keep the hidden private_state fully consistent with that exact start date."
      )
    obj = _openai_call(
      api_key=self.api_key,
      model=self.model,
      schema_name="intake_test_bootstrap",
      schema=schema,
      messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
      ],
    )
    business_start_date = str(obj["business_start_date"]).strip()
    private_state = str(obj["private_state"]).strip()
    if self.business_start_date_override:
      business_start_date = self.business_start_date_override
      private_state = (
        f"Business start date is exactly {self.business_start_date_override}. "
        f"{private_state}"
      ).strip()
    self.private_state = private_state
    return Bootstrap(
      business_name=str(obj["business_name"]).strip(),
      business_start_date=business_start_date,
      address=str(obj["address"]).strip(),
      address_street=str(obj["address_street"]).strip(),
      address_city=str(obj["address_city"]).strip(),
      address_state=str(obj["address_state"]).strip(),
      address_zip=str(obj["address_zip"]).strip(),
      address_country=str(obj["address_country"]).strip(),
      private_state=self.private_state,
    )

  def answer(
    self,
    *,
    active_focus: str,
    assistant_message: str,
    transcript_tail: List[Dict[str, str]],
  ) -> str:
    schema = {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "answer": {"type": "string"},
        "updated_private_state": {"type": "string"},
      },
      "required": ["answer", "updated_private_state"],
    }
    system = textwrap.dedent(
      """
      You are simulating a real business owner going through a business-plan intake chat.

      Rules:
      - Stay consistent with the hidden private state.
      - Answer naturally, as a human would.
      - Be concise unless the consultant clearly needs detail.
      - If the consultant asks a confusing question, push back briefly and ask for clarification.
      - If the consultant repeats a question you already answered, say so like a real user would.
      - If the consultant proposes a reasonable assumption that fits your business, you may agree briefly.
      - Do not mention the hidden private state or that you are a simulation.

      Return ONLY JSON matching the schema.
      updated_private_state should stay compact and reflect any clarified facts you just committed to.
      """
    ).strip()
    transcript_blob = json.dumps(transcript_tail[-12:], ensure_ascii=False)
    user = (
      f"Seed: {self.seed}\n"
      f"Current focus: {active_focus}\n"
      f"Hidden private state:\n{self.private_state}\n\n"
      f"Recent transcript tail (JSON):\n{transcript_blob}\n\n"
      f"Latest consultant message:\n{assistant_message}\n"
    )
    obj = _openai_call(
      api_key=self.api_key,
      model=self.model,
      schema_name="intake_test_turn",
      schema=schema,
      messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
      ],
    )
    self.private_state = str(obj["updated_private_state"]).strip() or self.private_state
    return str(obj["answer"]).strip()


def _print_transcript_tail(transcript: List[Dict[str, str]], count: int = 10) -> None:
  print("\nLast transcript turns:")
  for item in transcript[-count:]:
    role = item.get("role", "?")
    content = str(item.get("content") or "").strip()
    print(f"[{role}] {content}")


def _safe_filename_part(text: str, *, max_len: int = 80) -> str:
  cleaned = re.sub(r"[<>:\"/\\\\|?*]+", "", str(text or "").strip())
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  cleaned = cleaned.replace(".", "")
  return (cleaned[:max_len].rstrip() or "test-run")


def _eastern_now() -> datetime:
  return datetime.now(US_EASTERN)


def _build_run_artifact_path(*, output_dir: str, seed: str, written_at: datetime) -> str:
  date_part = written_at.strftime("%m-%d-%Y")
  scenario_part = _safe_filename_part(seed)
  return os.path.join(output_dir, f"{date_part} -- {scenario_part}.txt")


def _build_run_artifact_filename(*, seed: str, written_at: datetime) -> str:
  return os.path.basename(_build_run_artifact_path(output_dir="", seed=seed, written_at=written_at))


def _artifact_seed(*, seed: str, draft_id: Optional[str]) -> str:
  artifact_id = str(draft_id or "").strip()
  return artifact_id or seed


def _save_run_report(
  *,
  output_dir: str,
  seed: str,
  bootstrap: Optional[Bootstrap],
  transcript: List[Dict[str, str]],
  draft_id: Optional[str],
  status: str,
  stop_reason: str,
  written_at: Optional[datetime] = None,
) -> Optional[str]:
  try:
    os.makedirs(output_dir, exist_ok=True)
    now = written_at or _eastern_now()
    path = _build_run_artifact_path(output_dir=output_dir, seed=seed, written_at=now)

    lines: List[str] = []
    lines.append(f"Test Run: {seed}")
    lines.append(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if bootstrap:
      lines.append(f"Bootstrapped Business: {bootstrap.business_name}")
      lines.append(f"Business Start Date: {bootstrap.business_start_date}")
      lines.append(f"Address: {bootstrap.address}")
    if draft_id:
      lines.append(f"Draft ID: {draft_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Stop Reason: {stop_reason}")
    lines.append("")
    lines.append("Transcript")
    lines.append("----------")
    lines.append("")
    for item in transcript:
      role = str(item.get("role") or "?")
      focus = str(item.get("focus") or "").strip()
      content = str(item.get("content") or "").strip()
      if focus:
        lines.append(f"{role} [{focus}]: {content}")
      else:
        lines.append(f"{role}: {content}")
      lines.append("")

    with open(path, "w", encoding="utf-8") as handle:
      handle.write("\n".join(lines).rstrip() + "\n")
    return path
  except Exception:
    return None


def _fetch_persisted_state_snapshot(*, base_url: str, draft_id: Optional[str]) -> Dict[str, Any]:
  if not str(draft_id or "").strip():
    return {
      "status": "missing_draft_id",
      "detail": "No draft_id was available, so persisted state could not be fetched.",
    }

  draft_id_value = str(draft_id).strip()
  debug_url = f"{base_url}/debug/state/{draft_id_value}"
  try:
    payload = _get_json(debug_url, {})
    return {
      "status": "ok",
      "source": "debug/state",
      "payload": payload,
    }
  except Exception as exc:
    fallback_url = f"{base_url}/api/intake-consult/draft"
    try:
      fallback = _get_json(fallback_url, {"draft_id": draft_id_value})
      return {
        "status": "fallback",
        "source": "api/intake-consult/draft",
        "detail": f"Primary persisted-state fetch failed: {exc}",
        "payload": fallback,
      }
    except Exception as fallback_exc:
      return {
        "status": "error",
        "source": "debug/state",
        "detail": str(exc),
        "fallback_error": str(fallback_exc),
      }


def _save_persisted_state_report(
  *,
  base_url: str,
  output_dir: str,
  seed: str,
  bootstrap: Optional[Bootstrap],
  draft_id: Optional[str],
  client_id: Optional[str],
  status: str,
  stop_reason: str,
  written_at: Optional[datetime] = None,
) -> Optional[str]:
  try:
    os.makedirs(output_dir, exist_ok=True)
    now = written_at or _eastern_now()
    path = _build_run_artifact_path(output_dir=output_dir, seed=seed, written_at=now)
    snapshot = _fetch_persisted_state_snapshot(base_url=base_url, draft_id=draft_id)

    lines: List[str] = []
    lines.append(f"Test Run: {seed}")
    lines.append(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if bootstrap:
      lines.append(f"Bootstrapped Business: {bootstrap.business_name}")
      lines.append(f"Business Start Date: {bootstrap.business_start_date}")
      lines.append(f"Address: {bootstrap.address}")
    if draft_id:
      lines.append(f"Draft ID: {draft_id}")
    if client_id:
      lines.append(f"Client ID: {client_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Stop Reason: {stop_reason}")
    lines.append("")
    lines.append("Persisted State")
    lines.append("---------------")
    lines.append("")
    lines.append(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))

    with open(path, "w", encoding="utf-8") as handle:
      handle.write("\n".join(lines).rstrip() + "\n")
    return path
  except Exception:
    return None


def _detect_failure(
  *,
  transcript: List[Dict[str, str]],
  assistant_message: str,
  active_focus: str,
  turn_index: int,
  max_turns: int,
) -> Optional[str]:
  if not str(assistant_message or "").strip():
    return "assistant returned an empty message"
  if turn_index + 1 >= max_turns:
    return f"max turns reached ({max_turns})"

  assistant_msgs = [
    item for item in transcript if item.get("role") == "assistant" and str(item.get("focus") or "") == active_focus
  ]
  if len(assistant_msgs) >= 3:
    last_three = assistant_msgs[-3:]
    msg_a = str(last_three[-1].get("content") or "")
    msg_b = str(last_three[-2].get("content") or "")
    msg_c = str(last_three[-3].get("content") or "")
    if _similarity(msg_a, msg_b) >= 0.94 and _similarity(msg_a, msg_c) >= 0.90:
      return f"suspected loop in focus '{active_focus}' (assistant repeated substantially the same question)"

  user_msgs = [item for item in transcript if item.get("role") == "user"]
  if user_msgs and assistant_msgs:
    last_user = str(user_msgs[-1].get("content") or "")
    if _normalize(last_user) in {
      "i already answered this",
      "we already talked about this",
      "you already asked this",
      "i already answered this too",
    }:
      return f"user simulator flagged repetition in focus '{active_focus}'"
  return None


def _run_single_seed(
  *,
  seed: str,
  base_url: str,
  model: str,
  max_turns: int,
  output_dir: str,
  persisted_output_dir: str,
  business_start_date_override: Optional[str],
) -> int:
  api_key = os.getenv("OPENAI_API_KEY", "").strip()
  if not api_key:
    print("OPENAI_API_KEY is not set.", file=sys.stderr)
    return 2

  agent = ClientAgent(
    api_key=api_key,
    model=model,
    seed=seed,
    business_start_date_override=business_start_date_override,
  )
  transcript: List[Dict[str, str]] = []
  bootstrap: Optional[Bootstrap] = None
  draft_id: Optional[str] = None
  client_id: Optional[str] = None
  run_id = uuid.uuid4().hex
  run_started_at = _eastern_now()
  trace_file_name: Optional[str] = None
  run_started_perf = time.perf_counter()
  metrics = _SimulatorMetricsStore()
  metrics.create_run(
    run_id=run_id,
    seed=seed,
    model_name=model,
    base_url=base_url,
    output_dir=output_dir,
    started_at=run_started_at,
  )

  def _persist_report(*, status: str, stop_reason: str) -> None:
    written_at = _eastern_now()
    artifact_seed = _artifact_seed(seed=seed, draft_id=draft_id)
    path = _save_run_report(
      output_dir=output_dir,
      seed=artifact_seed,
      bootstrap=bootstrap,
      transcript=transcript,
      draft_id=draft_id,
      status=status,
      stop_reason=stop_reason,
      written_at=written_at,
    )
    if path:
      print(f"Saved run report: {path}")
    persisted_path = _save_persisted_state_report(
      base_url=base_url,
      output_dir=persisted_output_dir,
      seed=artifact_seed,
      bootstrap=bootstrap,
      draft_id=draft_id,
      client_id=client_id,
      status=status,
      stop_reason=stop_reason,
      written_at=written_at,
    )
    if persisted_path:
      print(f"Saved persisted state report: {persisted_path}")
    if trace_file_name:
      print(f"Expected terminal log file: {os.path.join(DEFAULT_TERMINAL_LOGS_DIR, trace_file_name)}")

  def _finish_metrics(*, status: str, stop_reason: str, total_turns: int) -> None:
    metrics.finish_run(
      run_id=run_id,
      ended_at=_eastern_now(),
      total_duration_ms=int(round((time.perf_counter() - run_started_perf) * 1000.0)),
      total_turns=total_turns,
      status=status,
      stop_reason=stop_reason,
    )
    metrics.close()

  try:
    bootstrap = agent.bootstrap()
    metrics.update_run_bootstrap(
      run_id=run_id,
      business_name=bootstrap.business_name,
      business_start_date=bootstrap.business_start_date,
      business_address=bootstrap.address,
    )
    print(f"Bootstrapped business: {bootstrap.business_name}")

    started = time.perf_counter()
    session = _post_json(f"{base_url}/api/intake-consult/session", {})
    session_create_ms = int(round((time.perf_counter() - started) * 1000.0))
    draft_id = session.get("draft_id")
    client_id = session.get("client_id")
    if not draft_id:
      raise RuntimeError(f"Failed to create draft session: {session}")
    trace_file_name = _build_run_artifact_filename(
      seed=_artifact_seed(seed=seed, draft_id=draft_id),
      written_at=run_started_at,
    )

    seed_payload = {
      "draft_id": draft_id,
      "client_id": client_id,
      "business_name": bootstrap.business_name,
      "business_start_date": bootstrap.business_start_date,
      "address": bootstrap.address,
      "address_street": bootstrap.address_street,
      "address_city": bootstrap.address_city,
      "address_state": bootstrap.address_state,
      "address_zip": bootstrap.address_zip,
      "address_country": bootstrap.address_country,
      "message": "",
    }
    trace_headers = {
      "X-Solver-Trace-Run-Name": trace_file_name,
      "X-Solver-Trace-Reset": "1",
    }
    started = time.perf_counter()
    response = _post_json(f"{base_url}/api/intake-consult", seed_payload, headers=trace_headers)
    initial_app_response_ms = int(round((time.perf_counter() - started) * 1000.0))
    metrics.update_run_session(
      run_id=run_id,
      draft_id=draft_id,
      client_id=client_id,
      session_create_ms=session_create_ms,
      initial_app_response_ms=initial_app_response_ms,
    )

    for turn_index in range(max_turns):
      turn_started_at = _eastern_now()
      draft_fetch_started = time.perf_counter()
      draft_snapshot = _get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
      draft_fetch_ms = int(round((time.perf_counter() - draft_fetch_started) * 1000.0))
      assistant_message = _render_fact_placeholders(
        str(response.get("assistant_message") or "").strip(),
        draft_snapshot,
      ).strip()
      active_focus = str(response.get("active_focus") or "").strip().lower()
      transcript.append({"role": "assistant", "content": assistant_message, "focus": active_focus})
      print(f"\n[{active_focus or 'unknown'}][assistant] {assistant_message}")

      if response.get("done"):
        print("\nSimulation completed.")
        draft = draft_snapshot
        print(
          "Final flags:",
          json.dumps(
            {
              "ops_confirmed": draft.get("ops_confirmed"),
              "market_confirmed": draft.get("market_confirmed"),
              "people_confirmed": draft.get("people_confirmed"),
              "financials_confirmed": draft.get("financials_confirmed"),
              "consistency_passed": draft.get("consistency_passed"),
            },
            ensure_ascii=False,
          ),
        )
        print(f"Draft ID: {draft_id}")
        metrics.insert_turn(
          run_id=run_id,
          turn_index=turn_index,
          focus=active_focus,
          turn_started_at=turn_started_at,
          draft_fetch_ms=draft_fetch_ms,
          client_answer_ms=None,
          app_response_ms=None,
          assistant_chars=len(assistant_message),
          user_chars=0,
          stop_flag=True,
          stop_reason="intake completed",
        )
        _finish_metrics(status="completed", stop_reason="intake completed", total_turns=turn_index + 1)
        _persist_report(status="completed", stop_reason="intake completed")
        return 0

      failure = _detect_failure(
        transcript=transcript,
        assistant_message=assistant_message,
        active_focus=active_focus,
        turn_index=turn_index,
        max_turns=max_turns,
      )
      if failure:
        print(f"\nSTOP: {failure}")
        print(f"Draft ID: {draft_id}")
        _print_transcript_tail(transcript)
        metrics.insert_turn(
          run_id=run_id,
          turn_index=turn_index,
          focus=active_focus,
          turn_started_at=turn_started_at,
          draft_fetch_ms=draft_fetch_ms,
          client_answer_ms=None,
          app_response_ms=None,
          assistant_chars=len(assistant_message),
          user_chars=0,
          stop_flag=True,
          stop_reason=failure,
        )
        _finish_metrics(status="stopped", stop_reason=failure, total_turns=turn_index + 1)
        _persist_report(status="stopped", stop_reason=failure)
        return 1

      client_answer_started = time.perf_counter()
      reply = agent.answer(
        active_focus=active_focus,
        assistant_message=assistant_message,
        transcript_tail=transcript,
      )
      client_answer_ms = int(round((time.perf_counter() - client_answer_started) * 1000.0))
      transcript.append({"role": "user", "content": reply, "focus": active_focus})
      print(f"[user] {reply}")

      app_response_started = time.perf_counter()
      response = _post_json(
        f"{base_url}/api/intake-consult",
        {
          "draft_id": draft_id,
          "client_id": client_id,
          "message": reply,
        },
        headers={"X-Solver-Trace-Run-Name": trace_file_name},
      )
      app_response_ms = int(round((time.perf_counter() - app_response_started) * 1000.0))
      metrics.insert_turn(
        run_id=run_id,
        turn_index=turn_index,
        focus=active_focus,
        turn_started_at=turn_started_at,
        draft_fetch_ms=draft_fetch_ms,
        client_answer_ms=client_answer_ms,
        app_response_ms=app_response_ms,
        assistant_chars=len(assistant_message),
        user_chars=len(reply),
        stop_flag=False,
        stop_reason="",
      )

    print(f"\nSTOP: max turns reached ({max_turns})")
    print(f"Draft ID: {draft_id}")
    _print_transcript_tail(transcript)
    _finish_metrics(status="stopped", stop_reason=f"max turns reached ({max_turns})", total_turns=max_turns)
    _persist_report(status="stopped", stop_reason=f"max turns reached ({max_turns})")
    return 1

  except KeyboardInterrupt:
    print("\nStopped by user.")
    _finish_metrics(status="stopped", stop_reason="stopped by user", total_turns=len([t for t in transcript if t.get("role") == "assistant"]))
    _persist_report(status="stopped", stop_reason="stopped by user")
    return 130
  except Exception as exc:
    print(f"\nSTOP: runner error: {type(exc).__name__}: {exc}")
    _print_transcript_tail(transcript)
    _finish_metrics(
      status="error",
      stop_reason=f"{type(exc).__name__}: {exc}",
      total_turns=len([t for t in transcript if t.get("role") == "assistant"]),
    )
    _persist_report(status="error", stop_reason=f"{type(exc).__name__}: {exc}")
    return 1


def main() -> int:
  _load_env()

  parser = argparse.ArgumentParser(
    description="Run a black-box dual-agent intake simulation against the real local app."
  )
  parser.add_argument(
    "seeds",
    nargs="+",
    help='One or more plain-English seeds, e.g. "Test a two-product local event services business"',
  )
  parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
  parser.add_argument("--model", default=os.getenv("INTAKE_SIM_MODEL", "gpt-4.1-mini"))
  parser.add_argument("--max-turns", type=int, default=80)
  parser.add_argument(
    "--business-start-date",
    default="",
    help='Optional exact business start date override in MM/DD/YYYY format.',
  )
  parser.add_argument(
    "--output-dir",
    default=DEFAULT_TEST_RUNS_DIR,
  )
  parser.add_argument(
    "--persisted-output-dir",
    default=DEFAULT_TEST_RUNS_DATA_DIR,
  )
  args = parser.parse_args()
  business_start_date_override = str(args.business_start_date or "").strip()
  if business_start_date_override:
    try:
      datetime.strptime(business_start_date_override, "%m/%d/%Y")
    except ValueError:
      print("--business-start-date must be in MM/DD/YYYY format.", file=sys.stderr)
      return 2

  base_url = args.base_url.rstrip("/")
  for index, seed in enumerate(args.seeds, start=1):
    if len(args.seeds) > 1:
      print(f"\n=== Scenario {index}/{len(args.seeds)}: {seed} ===\n")
    result = _run_single_seed(
      seed=seed,
      base_url=base_url,
      model=args.model,
      max_turns=args.max_turns,
      output_dir=args.output_dir,
      persisted_output_dir=args.persisted_output_dir,
      business_start_date_override=business_start_date_override or None,
    )
    if result != 0:
      return result
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
