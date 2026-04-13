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


def _default_apps_root() -> str:
  env_root = str(os.getenv("INTAKE_APPS_ROOT") or "").strip()
  if env_root:
    return env_root
  one_drive_root = str(os.getenv("OneDriveCommercial") or os.getenv("OneDrive") or "").strip()
  if one_drive_root:
    return os.path.join(one_drive_root, "Apps")
  return os.path.join(os.path.expanduser("~"), "OneDrive - Tithe Financial Wealth Management", "Apps")


DEFAULT_APPS_ROOT = _default_apps_root()
DEFAULT_TEST_RUNS_DIR = os.path.join(DEFAULT_APPS_ROOT, "Test Runs")
DEFAULT_TEST_RUNS_DATA_DIR = os.path.join(DEFAULT_APPS_ROOT, "Test Runs Data")
DEFAULT_TERMINAL_LOGS_DIR = os.path.join(DEFAULT_APPS_ROOT, "Terminal Logs")
DEFAULT_NEW_RUNNER_DIR = os.path.join(DEFAULT_APPS_ROOT, "New Runner")

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
  timeout: Optional[float] = None,
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


def _get_json(url: str, params: Dict[str, Any], *, timeout: Optional[float] = None) -> Dict[str, Any]:
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


def _parse_controller_resolution_state(*, planning_run_raw: Any = None, memo_raw: Any = None) -> Dict[str, Any]:
  planning_run = _parse_json_dict(planning_run_raw)
  memo = _parse_json_dict(memo_raw)

  def _normalize_issue_list(value: Any) -> List[Dict[str, str]]:
    source = value if isinstance(value, list) else []
    issues: List[Dict[str, str]] = []
    for item in source:
      if not isinstance(item, dict):
        continue
      issue_code = str(item.get("issue_code") or "").strip().lower()
      issue = str(item.get("issue") or "").strip()
      detail = str(item.get("detail") or "").strip()
      status = str(item.get("status") or "").strip().lower()
      if issue or detail or issue_code:
        payload = {"issue": issue, "detail": detail}
        if issue_code:
          payload["issue_code"] = issue_code
        if status:
          payload["status"] = status
        issues.append(payload)
    return issues

  state = (
    planning_run.get("controller_resolution_state")
    if isinstance(planning_run.get("controller_resolution_state"), dict)
    else {}
  )
  if not state and isinstance(memo.get("controller_resolution_state"), dict):
    state = memo.get("controller_resolution_state")

  detected = _normalize_issue_list(state.get("detected_issues"))
  remaining = _normalize_issue_list(state.get("remaining_issues"))
  resolved = _normalize_issue_list(state.get("resolved_issues"))
  return {
    "owner": str(state.get("owner") or "").strip() or "unknown",
    "status": str(state.get("status") or "").strip() or "missing",
    "display_status": str(state.get("display_status") or "").strip(),
    "all_cleared": bool(state.get("all_cleared")),
    "detected_issues": detected,
    "remaining_issues": remaining,
    "resolved_issues": resolved,
    "issue_status_records": _normalize_issue_list(state.get("issue_status_records")),
    "last_review_iteration": int(_safe_float(state.get("last_review_iteration")) or 0),
  }


def _parse_planning_run(raw: Any) -> Dict[str, Any]:
  planning_run = _parse_json_dict(raw)
  return planning_run if isinstance(planning_run, dict) else {}


def _realism_final_flags_from_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
  planning_run = _parse_planning_run(draft.get("planning_run_json"))
  state = _parse_controller_resolution_state(
    planning_run_raw=planning_run,
    memo_raw=draft.get("realism_memo_json"),
  )
  remaining = state.get("remaining_issues") if isinstance(state.get("remaining_issues"), list) else []
  status = str(state.get("status") or "").strip() or "missing"
  issue_count = len(remaining)
  return {
    "resolution_summary_status": status or "missing",
    "remaining_issue_count": issue_count,
  }


def _append_realism_memo_lines(lines: List[str], state: Dict[str, Any]) -> None:
  lines.append("Realism Memo:")
  lines.append(f"Owner: {str(state.get('owner') or '').strip() or 'missing'}")
  lines.append(f"Status: {str(state.get('status') or '').strip() or 'missing'}")
  detected = state.get("detected_issues") if isinstance(state.get("detected_issues"), list) else []
  remaining = state.get("remaining_issues") if isinstance(state.get("remaining_issues"), list) else []
  resolved = state.get("resolved_issues") if isinstance(state.get("resolved_issues"), list) else []
  lines.append(f"Detected Issue Count: {len(detected)}")
  lines.append(f"Remaining Issue Count: {len(remaining)}")
  lines.append(f"Resolved Issue Count: {len(resolved)}")
  if not remaining and not resolved:
    lines.append("No memo issues recorded.")
    return
  for item in remaining:
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    issue = str(item.get("issue") or "").strip()
    detail = str(item.get("detail") or "").strip()
    text = issue
    if detail:
      text = f"{text} {detail}".strip()
    if issue_code:
      text = f"[{issue_code}] {text}".strip()
    if text:
      lines.append(f"- {text}")
  if resolved:
    lines.append("Resolved Issues:")
    for item in resolved:
      if not isinstance(item, dict):
        continue
      issue_code = str(item.get("issue_code") or "").strip().lower()
      issue = str(item.get("issue") or "").strip()
      detail = str(item.get("detail") or "").strip()
      text = issue
      if detail:
        text = f"{text} {detail}".strip()
      if issue_code:
        text = f"[{issue_code}] {text}".strip()
      if text:
        lines.append(f"- {text}")


def _grid_exact_value_map(planning_run: Dict[str, Any]) -> Dict[str, Dict[int, float]]:
  gpt_meta = planning_run.get("gpt_grid_metadata") if isinstance(planning_run.get("gpt_grid_metadata"), dict) else {}
  response_payload = gpt_meta.get("response_json") if isinstance(gpt_meta.get("response_json"), dict) else {}
  legacy_grid_payload = gpt_meta.get("grid_json") if isinstance(gpt_meta.get("grid_json"), dict) else {}
  rows_payload = response_payload or legacy_grid_payload
  row_map: Dict[str, Dict[int, float]] = {}
  if not isinstance(rows_payload, dict):
    return row_map
  for row in [item for item in (rows_payload.get("rows") or []) if isinstance(item, dict)]:
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    lever_id = str(row.get("row_id") or "").strip()
    if not lever_id:
      continue
    quarter_map: Dict[int, float] = {}
    for entry in [item for item in (row.get("quarter_values") or []) if isinstance(item, dict)]:
      try:
        quarter_index = int(entry.get("quarter_index") or 0)
      except Exception:
        quarter_index = 0
      value = _safe_float(entry.get("value"))
      if quarter_index >= 1 and value is not None:
        quarter_map[quarter_index] = float(value)
    if quarter_map:
      row_map[lever_id] = quarter_map
  return row_map


def _append_realism_resolution_lines(lines: List[str], planning_run: Dict[str, Any], state: Dict[str, Any]) -> None:
  result = planning_run.get("realism_resolution_result") if isinstance(planning_run.get("realism_resolution_result"), dict) else {}
  decision = planning_run.get("realism_resolution_decision") if isinstance(planning_run.get("realism_resolution_decision"), dict) else {}
  verification = planning_run.get("realism_resolution_verification") if isinstance(planning_run.get("realism_resolution_verification"), dict) else {}
  updates = [item for item in (result.get("applied_updates") or []) if isinstance(item, dict)]
  lines.append("Realism Resolution:")
  lines.append(f"Review Status: {str(decision.get('status') or '').strip() or 'missing'}")
  lines.append(f"Result Status: {str(result.get('status') or '').strip() or 'missing'}")
  lines.append(f"Verification Status: {str(verification.get('status') or '').strip() or 'missing'}")
  lines.append(f"Iteration Count: {int(_safe_float(planning_run.get('realism_resolution_iteration_count')) or 0)}")
  lines.append(f"Stop Reason: {str(planning_run.get('realism_resolution_stop_reason') or '').strip() or 'missing'}")
  lines.append(f"Resolution Summary Status: {str(state.get('status') or '').strip() or 'missing'}")
  lines.append(f"All Cleared: {bool(state.get('all_cleared'))}")
  verification_payload = verification.get("verification") if isinstance(verification.get("verification"), dict) else {}
  if verification_payload:
    lines.append(f"Verification Assessment: {str(verification_payload.get('overall_assessment') or '').strip() or 'missing'}")
  lines.append(f"Applied Realism Updates: {len(updates)}")
  issue_results = [item for item in (verification_payload.get("issue_results") or []) if isinstance(item, dict)]
  if issue_results:
    lines.append("Verification Results:")
    for item in issue_results:
      code = str(item.get("issue_code") or "").strip()
      status = str(item.get("status") or "").strip()
      reason = str(item.get("verification_reason") or "").strip()
      quarters = [int(_safe_float(q) or 0) for q in (item.get("remaining_problem_quarters") or []) if int(_safe_float(q) or 0) >= 1]
      next_levers = [str(lever or "").strip() for lever in (item.get("next_required_lever_ids") or []) if str(lever or "").strip()]
      lines.append(f"- {code}: {status}")
      if reason:
        lines.append(f"  reason: {reason}")
      if quarters:
        lines.append(f"  remaining quarters: {', '.join(f'Q{q}' for q in quarters)}")
      if next_levers:
        lines.append(f"  next levers: {', '.join(next_levers)}")
  iterations = [item for item in (planning_run.get("realism_resolution_iterations") or []) if isinstance(item, dict)]
  if iterations:
    lines.append("Iteration Summary:")
    for item in iterations:
      iteration = int(_safe_float(item.get("iteration")) or 0)
      phase = str(item.get("phase") or "").strip() or "unknown"
      status = str(item.get("status") or "").strip() or "missing"
      active_issue_codes = [
        str(code or "").strip()
        for code in (item.get("active_issue_codes") or [])
        if str(code or "").strip()
      ]
      memo_after = item.get("memo_after") if isinstance(item.get("memo_after"), dict) else {}
      verification_after = item.get("verification_after") if isinstance(item.get("verification_after"), dict) else {}
      verification_payload = (
        verification_after.get("verification")
        if isinstance(verification_after.get("verification"), dict)
        else {}
      )
      remaining_after = [
        issue for issue in (memo_after.get("remaining_issues") or [])
        if isinstance(issue, dict)
      ]
      overall = str(verification_payload.get("overall_assessment") or "").strip() or "missing"
      active_text = ", ".join(active_issue_codes) if active_issue_codes else "none"
      lines.append(
        f"- Iteration {iteration} [{phase}] status={status}; active={active_text}; "
        f"remaining_after={len(remaining_after)}; verifier={overall}"
      )
      fresh_issue_candidates = [
        candidate for candidate in (item.get("fresh_issue_candidates") or [])
        if isinstance(candidate, dict)
      ]
      if fresh_issue_candidates:
        candidate_bits = []
        for candidate in fresh_issue_candidates:
          issue_code = str(candidate.get("issue_code") or candidate.get("issue") or "").strip()
          candidate_kind = str(candidate.get("candidate_kind") or "").strip() or "candidate"
          if issue_code:
            candidate_bits.append(f"{issue_code} ({candidate_kind})")
        if candidate_bits:
          lines.append(f"  fresh candidates: {', '.join(candidate_bits)}")
  if not updates:
    lines.append("No realism updates recorded.")
    return
  grid_map = _grid_exact_value_map(planning_run)
  lines.append("Realism Applied Updates (prior model -> realism):")
  for update in updates:
    lever_id = str(update.get("lever_id") or "").strip()
    quarter_index = int(_safe_float(update.get("quarter_index")) or 0)
    baseline_value = _safe_float(update.get("baseline_value"))
    grid_value = None
    if lever_id in grid_map:
      grid_value = grid_map[lever_id].get(quarter_index)
    before_value = baseline_value if baseline_value is not None else grid_value
    after_value = _safe_float(update.get("exact_value"))
    delta = None
    if before_value is not None and after_value is not None:
      delta = float(after_value - before_value)
    before_text = _format_number(before_value, money=False) if before_value is not None else "n/a"
    after_text = _format_number(after_value, money=False) if after_value is not None else "n/a"
    delta_text = _format_number(delta, money=False) if delta is not None else "n/a"
    reason = str(update.get("business_reason") or "").strip()
    lines.append(
      f"- Q{quarter_index} {lever_id}: {before_text} -> {after_text} (delta {delta_text})"
    )
    if reason:
      lines.append(f"  reason: {reason}")


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


def _parse_messages(raw: Any) -> List[Dict[str, str]]:
  source = raw
  if isinstance(raw, str):
    try:
      source = json.loads(raw)
    except Exception:
      source = []
  if not isinstance(source, list):
    return []
  messages: List[Dict[str, str]] = []
  for item in source:
    if not isinstance(item, dict):
      continue
    role = str(item.get("role") or "").strip() or "unknown"
    content = str(item.get("content") or "").strip()
    focus = str(item.get("focus") or "").strip()
    payload = {"role": role, "content": content}
    if focus:
      payload["focus"] = focus
    messages.append(payload)
  return messages


def _append_section(lines: List[str], title: str) -> None:
  lines.append(title)
  lines.append("-" * len(title))
  lines.append("")


def _diagnostics_snapshot(planning_run: Dict[str, Any]) -> Dict[str, Any]:
  snapshot = planning_run.get("diagnostics_snapshot") if isinstance(planning_run.get("diagnostics_snapshot"), dict) else {}
  return snapshot if isinstance(snapshot, dict) else {}


def _live_quarter_rows(finmo_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  rows = [item for item in (finmo_json.get("quarter_rows") or []) if isinstance(item, dict)]
  out: List[Dict[str, Any]] = []
  for item in rows:
    try:
      quarter_index = int(item.get("quarter_index") or 0)
    except Exception:
      quarter_index = 0
    if quarter_index >= 1:
      out.append(item)
  return out


def _statement_rows(finmo_json: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
  return [item for item in (finmo_json.get(key) or []) if isinstance(item, dict)]


def _annualize_statement_rows(rows: List[Dict[str, Any]], *, mode: str) -> List[Dict[str, Any]]:
  annual_rows: List[Dict[str, Any]] = []
  for row in rows:
    label = str(row.get("label") or "").strip()
    values = [float(_safe_float(item) or 0.0) for item in (row.get("values") or [])]
    annual_values: List[float] = []
    for start in range(0, len(values), 4):
      chunk = values[start:start + 4]
      if not chunk:
        continue
      if mode == "ending":
        annual_values.append(float(chunk[-1]))
      else:
        annual_values.append(float(sum(chunk)))
    annual_rows.append({"label": label, "values": annual_values})
  return annual_rows


def _append_statement_matrix(
  lines: List[str],
  *,
  title: str,
  rows: List[Dict[str, Any]],
  period_prefix: str,
  money: bool,
) -> None:
  _append_section(lines, title)
  if not rows:
    lines.append("No data available.")
    lines.append("")
    return
  max_periods = max((len(list(item.get("values") or [])) for item in rows), default=0)
  header = ["Row"] + [f"{period_prefix}{index}" for index in range(1, max_periods + 1)]
  lines.append(" | ".join(header))
  for row in rows:
    label = str(row.get("label") or "").strip() or "Unnamed Row"
    values = list(row.get("values") or [])
    formatted = [_format_number(value, money=money) for value in values]
    padded = formatted + ["" for _ in range(max(0, max_periods - len(formatted)))]
    lines.append(" | ".join([label, *padded[:max_periods]]))
  lines.append("")


def _append_accounting_equation_section(lines: List[str], finmo_json: Dict[str, Any]) -> None:
  accounting = finmo_json.get("accounting_check") if isinstance(finmo_json.get("accounting_check"), dict) else {}
  status_values = list(accounting.get("status_values") or [])
  numeric_values = list(accounting.get("numeric_values") or [])
  _append_section(lines, "Accounting Equation")
  lines.append(f"All OK: {bool(accounting.get('all_ok'))}")
  if not status_values and not numeric_values:
    lines.append("No accounting equation diagnostics available.")
    lines.append("")
    return
  lines.append("Quarter | Status | Difference")
  quarter_count = max(len(status_values), len(numeric_values))
  for idx in range(quarter_count):
    status = str(status_values[idx] if idx < len(status_values) else "").strip() or "n/a"
    numeric = numeric_values[idx] if idx < len(numeric_values) else None
    lines.append(f"Q{idx + 1} | {status} | {_format_number(numeric, money=True)}")
  if numeric_values:
    lines.append("")
    lines.append("Year-End Accounting Equation Check")
    lines.append("Year | Status | Difference")
    for year_index, quarter_index in enumerate(range(4, len(numeric_values) + 1, 4), start=1):
      status = str(status_values[quarter_index - 1] if quarter_index - 1 < len(status_values) else "").strip() or "n/a"
      numeric = numeric_values[quarter_index - 1] if quarter_index - 1 < len(numeric_values) else None
      lines.append(f"Y{year_index} | {status} | {_format_number(numeric, money=True)}")
  lines.append("")


def _controller_catalog_map(model_input_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  catalog: Dict[str, Dict[str, Any]] = {}
  for item in (model_input_json.get("controller_write_levers") or []):
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if lever_id:
      catalog[lever_id] = dict(item)
  lever_catalog = model_input_json.get("lever_catalog") if isinstance(model_input_json.get("lever_catalog"), dict) else {}
  for lever_id, item in lever_catalog.items():
    if not isinstance(item, dict):
      continue
    lever_key = str(lever_id or "").strip()
    if lever_key and lever_key not in catalog:
      payload = dict(item)
      payload["lever_id"] = lever_key
      catalog[lever_key] = payload
  return catalog


def _iter_model_input_rows(model_input_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  sections = model_input_json.get("sections") if isinstance(model_input_json.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_name in ("revenue", "expenses", "balance_sheet"):
    for row in (sections.get(section_name) or []):
      if isinstance(row, dict):
        payload = dict(row)
        payload["_section_name"] = section_name
        rows.append(payload)
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in (schedules.get("rows") or []):
    if isinstance(row, dict):
      payload = dict(row)
      payload["_section_name"] = "schedules"
      rows.append(payload)
  return rows


def _model_input_report_rows(model_input_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  catalog = _controller_catalog_map(model_input_json)
  out: List[Dict[str, Any]] = []
  for row in _iter_model_input_rows(model_input_json):
    lever_id = str(row.get("controller_write_lever_id") or row.get("lever_id") or "").strip()
    values = list(row.get("values") or [])
    if len(values) == 21:
      values = values[1:]
    if not any(abs(float(_safe_float(item) or 0.0)) > 1e-9 for item in values):
      continue
    meta = catalog.get(lever_id) or {}
    label = (
      str(meta.get("label_path") or "").strip()
      or str(row.get("label") or "").strip()
      or str(row.get("driver") or "").strip()
      or lever_id
      or "Unnamed Row"
    )
    out.append(
      {
        "section": str(row.get("_section_name") or meta.get("section") or "").strip() or "unknown",
        "lever_id": lever_id,
        "label": label,
        "values": [float(_safe_float(item) or 0.0) for item in values[:20]],
      }
    )
  out.sort(key=lambda item: (str(item.get("section") or ""), str(item.get("label") or "")))
  return out


def _model_input_value_map(model_input_json: Dict[str, Any]) -> Dict[str, List[float]]:
  value_map: Dict[str, List[float]] = {}
  for item in _model_input_report_rows(model_input_json):
    lever_id = str(item.get("lever_id") or "").strip()
    if lever_id:
      value_map[lever_id] = [float(_safe_float(v) or 0.0) for v in (item.get("values") or [])]
  return value_map


def _append_model_input_stage(lines: List[str], *, title: str, model_input_json: Dict[str, Any]) -> None:
  _append_section(lines, title)
  rows = _model_input_report_rows(model_input_json)
  if not rows:
    lines.append("No model-input stage snapshot available.")
    lines.append("")
    return
  header = ["Section", "Lever", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10", "Q11", "Q12", "Q13", "Q14", "Q15", "Q16", "Q17", "Q18", "Q19", "Q20"]
  lines.append(" | ".join(header))
  for item in rows:
    values = [_format_number(value, money=False) for value in (item.get("values") or [])]
    padded = values + ["" for _ in range(max(0, 20 - len(values)))]
    lines.append(
      " | ".join(
        [
          str(item.get("section") or ""),
          str(item.get("label") or item.get("lever_id") or ""),
          *padded[:20],
        ]
      )
    )
  lines.append("")


def _append_model_input_diff(
  lines: List[str],
  *,
  title: str,
  before_model_input_json: Dict[str, Any],
  after_model_input_json: Dict[str, Any],
) -> None:
  _append_section(lines, title)
  before_map = _model_input_value_map(before_model_input_json)
  after_map = _model_input_value_map(after_model_input_json)
  catalog = _controller_catalog_map(after_model_input_json or before_model_input_json)
  diff_lines: List[str] = []
  for lever_id in sorted(set(before_map.keys()) | set(after_map.keys())):
    before_values = before_map.get(lever_id) or []
    after_values = after_map.get(lever_id) or []
    max_len = max(len(before_values), len(after_values), 20)
    for idx in range(max_len):
      before_value = float(before_values[idx]) if idx < len(before_values) else 0.0
      after_value = float(after_values[idx]) if idx < len(after_values) else 0.0
      if abs(after_value - before_value) <= 1e-9:
        continue
      meta = catalog.get(lever_id) or {}
      label = str(meta.get("label_path") or "").strip() or lever_id
      diff_lines.append(
        f"Q{idx + 1} | {label} | {_format_number(before_value, money=False)} -> {_format_number(after_value, money=False)} | delta {_format_number(after_value - before_value, money=False)}"
      )
  if not diff_lines:
    lines.append("No model-input changes in this stage.")
  else:
    lines.extend(diff_lines)
  lines.append("")


def _append_conversation(lines: List[str], messages: List[Dict[str, str]]) -> None:
  _append_section(lines, "Full Intake Conversation")
  if not messages:
    lines.append("No persisted conversation available.")
    lines.append("")
    return
  for item in messages:
    role = str(item.get("role") or "unknown").strip() or "unknown"
    focus = str(item.get("focus") or "").strip()
    content = str(item.get("content") or "").strip()
    if focus:
      lines.append(f"{role} [{focus}]: {content}")
    else:
      lines.append(f"{role}: {content}")
    lines.append("")


def _append_controller_state(lines: List[str], state: Dict[str, Any]) -> None:
  _append_section(lines, "Resolution Status")
  lines.append(f"Owner: {str(state.get('owner') or '').strip() or 'missing'}")
  lines.append(f"Status: {str(state.get('status') or '').strip() or 'missing'}")
  lines.append(f"All Cleared: {bool(state.get('all_cleared'))}")
  lines.append(f"Detected: {len(state.get('detected_issues') or [])}")
  lines.append(f"Resolved: {len(state.get('resolved_issues') or [])}")
  lines.append(f"Open: {len(state.get('remaining_issues') or [])}")
  lines.append("")
  issue_records = [item for item in (state.get("issue_status_records") or []) if isinstance(item, dict)]
  if issue_records:
    lines.append("Issue Status Records:")
    for item in issue_records:
      issue_code = str(item.get("issue_code") or item.get("issue") or "").strip()
      status = str(item.get("status") or "").strip() or "unknown"
      detail = str(item.get("detail") or "").strip()
      lines.append(f"- {issue_code}: {status}")
      if detail:
        lines.append(f"  detail: {detail}")
  else:
    lines.append("No issue status records available.")
  lines.append("")


def _append_realism_iteration_details(lines: List[str], planning_run: Dict[str, Any]) -> None:
  iterations = [item for item in (planning_run.get("realism_resolution_iterations") or []) if isinstance(item, dict)]
  _append_section(lines, "Realism Iteration Diagnostics")
  if not iterations:
    lines.append("No realism iterations recorded.")
    lines.append("")
    return
  main_iterations = [item for item in iterations if str(item.get("phase") or "").strip().lower() != "cleanup"]
  cleanup_iterations = [item for item in iterations if str(item.get("phase") or "").strip().lower() == "cleanup"]
  lines.append(f"Standard Iteration Count: {len(main_iterations)}")
  lines.append(f"New-Issue / Cleanup Pass Count: {len(cleanup_iterations)}")
  lines.append("")
  for item in iterations:
    iteration = int(_safe_float(item.get("iteration")) or 0)
    phase = str(item.get("phase") or "").strip() or "unknown"
    status = str(item.get("status") or "").strip() or "missing"
    active_issue_codes = [str(code or "").strip() for code in (item.get("active_issue_codes") or []) if str(code or "").strip()]
    decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
    plan = item.get("plan") if isinstance(item.get("plan"), dict) else {}
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    verification_after = item.get("verification_after") if isinstance(item.get("verification_after"), dict) else {}
    verification_payload = verification_after.get("verification") if isinstance(verification_after.get("verification"), dict) else {}
    memo_after = item.get("memo_after") if isinstance(item.get("memo_after"), dict) else {}
    controller_after = memo_after.get("controller_resolution_state") if isinstance(memo_after.get("controller_resolution_state"), dict) else {}
    lines.append(f"Iteration {iteration} [{phase}]")
    lines.append(f"Status: {status}")
    lines.append(f"Active Issues In: {', '.join(active_issue_codes) if active_issue_codes else 'none'}")
    lines.append(f"Decision Status: {str(decision.get('status') or '').strip() or 'missing'}")
    lines.append(f"Plan Status: {str(plan.get('status') or '').strip() or 'missing'}")
    lines.append(f"Result Status: {str(result.get('status') or '').strip() or 'missing'}")
    lines.append(f"Verifier Status: {str(verification_after.get('status') or '').strip() or 'missing'}")
    lines.append(f"Verifier Assessment: {str(verification_payload.get('overall_assessment') or '').strip() or 'missing'}")
    lines.append(f"Open Issues After: {len(controller_after.get('remaining_issues') or [])}")
    issue_results = [entry for entry in (verification_payload.get("issue_results") or []) if isinstance(entry, dict)]
    if issue_results:
      lines.append("Issue Results:")
      for entry in issue_results:
        code = str(entry.get("issue_code") or "").strip()
        verdict = str(entry.get("status") or "").strip()
        reason = str(entry.get("verification_reason") or "").strip()
        next_levers = [str(lever or "").strip() for lever in (entry.get("next_required_lever_ids") or []) if str(lever or "").strip()]
        lines.append(f"- {code}: {verdict}")
        if reason:
          lines.append(f"  reason: {reason}")
        if next_levers:
          lines.append(f"  next levers: {', '.join(next_levers)}")
    applied_updates = [entry for entry in (result.get("applied_updates") or []) if isinstance(entry, dict)]
    if applied_updates:
      lines.append("Applied Updates:")
      for entry in applied_updates:
        lever_id = str(entry.get("lever_id") or "").strip()
        quarter_index = int(_safe_float(entry.get("quarter_index")) or 0)
        baseline_value = _safe_float(entry.get("baseline_value"))
        exact_value = _safe_float(entry.get("exact_value"))
        lines.append(
          f"- Q{quarter_index} {lever_id}: {_format_number(baseline_value, money=False)} -> {_format_number(exact_value, money=False)}"
        )
    fresh_issue_candidates = [entry for entry in (item.get("fresh_issue_candidates") or []) if isinstance(entry, dict)]
    if fresh_issue_candidates:
      lines.append("Fresh Issue Candidates:")
      for entry in fresh_issue_candidates:
        issue_code = str(entry.get("issue_code") or entry.get("issue") or "").strip()
        candidate_kind = str(entry.get("candidate_kind") or "").strip() or "candidate"
        detail = str(entry.get("detail") or "").strip()
        lines.append(f"- {issue_code}: {candidate_kind}")
        if detail:
          lines.append(f"  detail: {detail}")
    lines.append("")


def _append_strategy_section(lines: List[str], planning_run: Dict[str, Any]) -> None:
  review_context = planning_run.get("cash_strategy_review_context") if isinstance(planning_run.get("cash_strategy_review_context"), dict) else {}
  review_decision = planning_run.get("cash_strategy_review_decision") if isinstance(planning_run.get("cash_strategy_review_decision"), dict) else {}
  second_pass_plan = planning_run.get("cash_strategy_second_pass_plan") if isinstance(planning_run.get("cash_strategy_second_pass_plan"), dict) else {}
  second_pass_result = planning_run.get("cash_strategy_second_pass_result") if isinstance(planning_run.get("cash_strategy_second_pass_result"), dict) else {}
  effect_summary = planning_run.get("cash_strategy_effect_summary") if isinstance(planning_run.get("cash_strategy_effect_summary"), dict) else {}
  _append_section(lines, "Final Strategy Pass")
  lines.append(f"Selected Cash Strategy: {str(effect_summary.get('selected_cash_strategy') or review_decision.get('selected_cash_strategy') or '').strip() or 'missing'}")
  lines.append(f"Review Status: {str(effect_summary.get('review_status') or review_decision.get('review_status') or '').strip() or 'missing'}")
  lines.append(f"Decision Trigger Type: {str(effect_summary.get('decision_trigger_type') or review_decision.get('decision_trigger_type') or '').strip() or 'missing'}")
  lines.append(f"Recommendation Mode: {str(effect_summary.get('recommendation_mode') or review_decision.get('recommendation_mode') or '').strip() or 'missing'}")
  lines.append(f"Second Pass Status: {str(effect_summary.get('second_pass_status') or second_pass_result.get('status') or '').strip() or 'missing'}")
  lines.append(f"Recommended Action Count: {int(_safe_float(effect_summary.get('recommended_action_count')) or 0)}")
  lines.append(f"Applied Control Count: {int(_safe_float(effect_summary.get('applied_control_count')) or 0)}")
  lines.append(f"Material Change Detected: {bool(effect_summary.get('material_change_detected'))}")
  if str(effect_summary.get("summary_line") or "").strip():
    lines.append(f"Summary: {str(effect_summary.get('summary_line') or '').strip()}")
  if str(review_decision.get("decision_trigger_summary") or "").strip():
    lines.append(f"Decision Trigger Summary: {str(review_decision.get('decision_trigger_summary') or '').strip()}")
  if str(review_decision.get("executive_summary") or "").strip():
    lines.append(f"Executive Summary: {str(review_decision.get('executive_summary') or '').strip()}")
  trigger_candidates = [item for item in (review_context.get("decision_trigger_candidates") or []) if isinstance(item, dict)]
  if trigger_candidates:
    lines.append("Decision Trigger Candidates:")
    for item in trigger_candidates:
      lines.append(
        f"- {str(item.get('trigger_type') or '').strip() or 'unknown'} :: {str(item.get('trigger_code') or '').strip() or 'unknown'}"
      )
  recommended_actions = [item for item in (review_decision.get("recommended_actions") or []) if isinstance(item, dict)]
  if recommended_actions:
    lines.append("Recommended Actions:")
    for item in recommended_actions:
      lines.append(json.dumps(item, ensure_ascii=False, default=str))
  planned_controls = [item for item in (second_pass_plan.get("controls") or []) if isinstance(item, dict)]
  if planned_controls:
    lines.append("Second-Pass Planned Controls:")
    for item in planned_controls:
      lines.append(json.dumps(item, ensure_ascii=False, default=str))
  applied_updates = [item for item in (second_pass_result.get("applied_updates") or []) if isinstance(item, dict)]
  if applied_updates:
    lines.append("Second-Pass Applied Updates:")
    for item in applied_updates:
      lines.append(
        f"- Q{int(_safe_float(item.get('quarter_index')) or 0)} {str(item.get('lever_id') or '').strip()}: "
        f"{_format_number(item.get('baseline_value'), money=False)} -> {_format_number(item.get('exact_value'), money=False)}"
      )
  else:
    lines.append("Second-Pass Applied Updates: none")
  lines.append("Effect Deltas:")
  lines.append(f"- Final Cash Delta: {_format_number(effect_summary.get('delta_final_cash'), money=True)}")
  lines.append(f"- Peak Cash Delta: {_format_number(effect_summary.get('delta_peak_cash'), money=True)}")
  lines.append(f"- Changed Cash Quarter Count: {int(_safe_float(effect_summary.get('changed_cash_quarter_count')) or 0)}")
  delta_summary = effect_summary.get("delta_summary") if isinstance(effect_summary.get("delta_summary"), dict) else {}
  for key in (
    "marketing_total_delta",
    "payroll_total_delta",
    "capital_expenditures_total_delta",
    "principal_repayment_total_delta",
  ):
    lines.append(f"- {key}: {_format_number(delta_summary.get(key), money=True)}")
  lines.append("")


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


def _build_named_artifact_path(*, output_dir: str, seed: str, written_at: datetime, suffix: str) -> str:
  date_part = written_at.strftime("%m-%d-%Y")
  scenario_part = _safe_filename_part(seed)
  suffix_part = _safe_filename_part(suffix)
  return os.path.join(output_dir, f"{date_part} -- {scenario_part} -- {suffix_part}.txt")


def _build_run_artifact_filename(*, seed: str, written_at: datetime) -> str:
  return os.path.basename(_build_run_artifact_path(output_dir="", seed=seed, written_at=written_at))


def _artifact_seed(*, seed: str, draft_id: Optional[str]) -> str:
  artifact_id = str(draft_id or "").strip()
  return artifact_id or seed


def _save_run_report(
  *,
  base_url: str,
  output_dir: str,
  seed: str,
  bootstrap: Optional[Bootstrap],
  transcript: List[Dict[str, str]],
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
    row = (
      (((snapshot.get("payload") or {}) if isinstance(snapshot.get("payload"), dict) else {}).get("row") or {})
      if isinstance(snapshot, dict)
      else {}
    )
    planning_run = _parse_planning_run(row.get("planning_run_json"))
    controller_state = _parse_controller_resolution_state(
      planning_run_raw=planning_run,
      memo_raw=(row or {}).get("realism_memo_json"),
    )
    diagnostics = _diagnostics_snapshot(planning_run)
    messages = _parse_messages((row or {}).get("messages_json"))
    baseline_model_input_json = diagnostics.get("baseline_model_input_json") if isinstance(diagnostics.get("baseline_model_input_json"), dict) else {}
    baseline_finmo_json = diagnostics.get("baseline_finmo_json") if isinstance(diagnostics.get("baseline_finmo_json"), dict) else {}
    grid_applied_model_input_json = diagnostics.get("grid_applied_model_input_json") if isinstance(diagnostics.get("grid_applied_model_input_json"), dict) else {}
    grid_applied_finmo_json = diagnostics.get("grid_applied_finmo_json") if isinstance(diagnostics.get("grid_applied_finmo_json"), dict) else {}
    realism_resolved_model_input_json = diagnostics.get("realism_resolved_model_input_json") if isinstance(diagnostics.get("realism_resolved_model_input_json"), dict) else {}
    realism_resolved_finmo_json = diagnostics.get("realism_resolved_finmo_json") if isinstance(diagnostics.get("realism_resolved_finmo_json"), dict) else {}
    final_model_input_json = diagnostics.get("final_model_input_json") if isinstance(diagnostics.get("final_model_input_json"), dict) else {}
    final_finmo_json = diagnostics.get("final_finmo_json") if isinstance(diagnostics.get("final_finmo_json"), dict) else {}
    if not final_model_input_json and isinstance(row.get("model_input_json"), dict):
      final_model_input_json = dict(row.get("model_input_json") or {})
    if not final_finmo_json and isinstance(row.get("finmo_json"), dict):
      final_finmo_json = dict(row.get("finmo_json") or {})
    if not realism_resolved_model_input_json:
      realism_resolved_model_input_json = dict(final_model_input_json or {})
    if not realism_resolved_finmo_json:
      realism_resolved_finmo_json = dict(final_finmo_json or {})
    if not grid_applied_model_input_json:
      grid_applied_model_input_json = dict(realism_resolved_model_input_json or {})
    if not grid_applied_finmo_json:
      grid_applied_finmo_json = dict(realism_resolved_finmo_json or {})
    if not baseline_model_input_json:
      baseline_model_input_json = dict(grid_applied_model_input_json or {})
    if not baseline_finmo_json:
      baseline_finmo_json = dict(grid_applied_finmo_json or {})
    transcript_for_appendix = messages or transcript

    lines: List[str] = []
    lines.append(f"Master Run Report: {seed}")
    lines.append(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if bootstrap:
      lines.append(f"Bootstrapped Business: {bootstrap.business_name}")
      lines.append(f"Business Start Date: {bootstrap.business_start_date}")
      lines.append(f"Address: {bootstrap.address}")
    if isinstance(row, dict) and row:
      lines.append(f"Business Name: {str(row.get('business_name') or '').strip() or (bootstrap.business_name if bootstrap else '')}")
    if draft_id:
      lines.append(f"Draft ID: {draft_id}")
    if client_id:
      lines.append(f"Client ID: {client_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Stop Reason: {stop_reason}")
    lines.append("")
    _append_controller_state(lines, controller_state)
    _append_accounting_equation_section(lines, final_finmo_json)
    _append_realism_memo_lines(lines, controller_state)
    lines.append("")
    _append_realism_resolution_lines(lines, planning_run, controller_state)
    lines.append("")
    _append_realism_iteration_details(lines, planning_run)
    _append_strategy_section(lines, planning_run)
    _append_statement_matrix(
      lines,
      title="P&L By Quarter",
      rows=_statement_rows(final_finmo_json, "pl"),
      period_prefix="Q",
      money=True,
    )
    _append_statement_matrix(
      lines,
      title="P&L By Year",
      rows=_annualize_statement_rows(_statement_rows(final_finmo_json, "pl"), mode="sum"),
      period_prefix="Y",
      money=True,
    )
    _append_statement_matrix(
      lines,
      title="Balance Sheet By Quarter",
      rows=_statement_rows(final_finmo_json, "balance_sheet"),
      period_prefix="Q",
      money=True,
    )
    _append_statement_matrix(
      lines,
      title="Balance Sheet By Year",
      rows=_annualize_statement_rows(_statement_rows(final_finmo_json, "balance_sheet"), mode="ending"),
      period_prefix="Y",
      money=True,
    )
    _append_statement_matrix(
      lines,
      title="Cash Flow By Quarter",
      rows=_statement_rows(final_finmo_json, "cash_flow"),
      period_prefix="Q",
      money=True,
    )
    _append_statement_matrix(
      lines,
      title="Cash Flow By Year",
      rows=_annualize_statement_rows(_statement_rows(final_finmo_json, "cash_flow"), mode="sum"),
      period_prefix="Y",
      money=True,
    )
    _append_model_input_stage(lines, title="Initial Base Spread Model Input", model_input_json=baseline_model_input_json)
    _append_model_input_stage(lines, title="Grid-Applied Model Input", model_input_json=grid_applied_model_input_json)
    _append_model_input_diff(
      lines,
      title="Diff: Base Spread -> Grid Applied",
      before_model_input_json=baseline_model_input_json,
      after_model_input_json=grid_applied_model_input_json,
    )
    _append_model_input_stage(lines, title="Realism-Resolved Model Input", model_input_json=realism_resolved_model_input_json)
    _append_model_input_diff(
      lines,
      title="Diff: Grid Applied -> Realism Resolved",
      before_model_input_json=grid_applied_model_input_json,
      after_model_input_json=realism_resolved_model_input_json,
    )
    _append_model_input_stage(lines, title="Final Strategy Model Input", model_input_json=final_model_input_json)
    _append_model_input_diff(
      lines,
      title="Diff: Realism Resolved -> Final Strategy",
      before_model_input_json=realism_resolved_model_input_json,
      after_model_input_json=final_model_input_json,
    )
    _append_conversation(lines, messages)
    _append_section(lines, "Run Transcript Appendix")
    if transcript:
      for item in transcript:
        role = str(item.get("role") or "?")
        focus = str(item.get("focus") or "").strip()
        content = str(item.get("content") or "").strip()
        if focus:
          lines.append(f"{role} [{focus}]: {content}")
        else:
          lines.append(f"{role}: {content}")
        lines.append("")
    else:
      lines.append("No local simulator transcript available.")
      lines.append("")
    _append_section(lines, "Raw Planning Payload Appendix")
    lines.append(json.dumps(planning_run, indent=2, ensure_ascii=False, default=str))
    lines.append("")
    _append_section(lines, "Raw Controller State Appendix")
    lines.append(json.dumps(controller_state, indent=2, ensure_ascii=False, default=str))
    lines.append("")
    _append_section(lines, "Raw Persisted Snapshot Appendix")
    lines.append(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))

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
    row = (
      (((snapshot.get("payload") or {}) if isinstance(snapshot.get("payload"), dict) else {}).get("row") or {})
      if isinstance(snapshot, dict)
      else {}
    )
    planning_run = _parse_planning_run(row.get("planning_run_json"))
    controller_state = _parse_controller_resolution_state(
      planning_run_raw=planning_run,
      memo_raw=(row or {}).get("realism_memo_json"),
    )

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
    _append_realism_memo_lines(lines, controller_state)
    lines.append("")
    _append_realism_resolution_lines(lines, planning_run, controller_state)
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


def _annual_summary_from_quarter_rows(quarter_rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, float]]:
  summary: Dict[int, Dict[str, float]] = {}
  ending_keys = {
    "ending_cash",
    "cash",
    "accounts_receivable",
    "inventory",
    "prepaid_expenses",
    "ppe",
    "accumulated_depreciation",
    "accounts_payable",
    "deferred_revenue",
    "lease_closing_balance_total",
    "short_term_debt",
    "long_term_debt",
    "owners_capital",
    "other_equity",
    "retained_earnings",
    "total_assets",
    "total_liabilities_and_equity",
    "accounting_equation_check",
  }
  for row in quarter_rows:
    try:
      quarter_index = int(row.get("quarter_index") or 0)
    except Exception:
      quarter_index = 0
    if quarter_index <= 0:
      continue
    year_index = ((quarter_index - 1) // 4) + 1
    bucket = summary.setdefault(year_index, {})
    for key, value in row.items():
      if key in {"quarter_index", "quarter", "date", "year", "slot_index"}:
        continue
      try:
        number = float(value)
      except Exception:
        continue
      if key in ending_keys:
        bucket[key] = number
      else:
        bucket[key] = bucket.get(key, 0.0) + number
  return summary


def _save_new_runner_report(
  *,
  base_url: str,
  output_dir: str,
  seed: str,
  bootstrap: Optional[Bootstrap],
  draft_id: Optional[str],
  written_at: Optional[datetime] = None,
) -> Optional[str]:
  try:
    os.makedirs(output_dir, exist_ok=True)
    now = written_at or _eastern_now()
    path = _build_run_artifact_path(output_dir=output_dir, seed=seed, written_at=now)
    snapshot = _fetch_persisted_state_snapshot(base_url=base_url, draft_id=draft_id)
    row = (
      (((snapshot.get("payload") or {}) if isinstance(snapshot.get("payload"), dict) else {}).get("row") or {})
      if isinstance(snapshot, dict)
      else {}
    )
    if not isinstance(row, dict) or not row:
      return None

    planning_run = _parse_planning_run(row.get("planning_run_json"))
    finmo_json = row.get("finmo_json") if isinstance(row.get("finmo_json"), dict) else {}
    controller_state = _parse_controller_resolution_state(
      planning_run_raw=planning_run,
      memo_raw=row.get("realism_memo_json"),
    )
    quarter_rows = [item for item in (finmo_json.get("quarter_rows") or []) if isinstance(item, dict)]
    accounting_check = finmo_json.get("accounting_check") if isinstance(finmo_json.get("accounting_check"), dict) else {}
    gpt_meta = planning_run.get("gpt_grid_metadata") if isinstance(planning_run.get("gpt_grid_metadata"), dict) else {}
    application_summary = planning_run.get("grid_application_summary") if isinstance(planning_run.get("grid_application_summary"), dict) else {}
    validation = gpt_meta.get("validation") if isinstance(gpt_meta.get("validation"), dict) else {}
    annual = _annual_summary_from_quarter_rows(quarter_rows)

    lines: List[str] = []
    lines.append(f"Business Name: {str(row.get('business_name') or '').strip()}")
    lines.append(f"Draft ID: {str(draft_id or row.get('draft_id') or '').strip()}")
    if bootstrap:
      lines.append(f"Business Start Date: {bootstrap.business_start_date}")
    lines.append(f"Planning Mode: {str(planning_run.get('planning_mode') or '').strip()}")
    lines.append(f"Planning Mode Reason: {str(planning_run.get('planning_mode_reason') or '').strip()}")
    lines.append(f"Prompt File: {str(planning_run.get('prompt_file') or '').strip()}")
    lines.append(f"GPT Rows Requested: {gpt_meta.get('requested_row_count')}")
    lines.append(f"GPT Rows Returned: {gpt_meta.get('returned_row_count')}")
    lines.append(f"Missing Rows: {len(validation.get('missing_rows') or [])}")
    lines.append(f"Extra Rows: {len(validation.get('extra_rows') or [])}")
    lines.append(f"Malformed Rows: {len(validation.get('malformed_rows') or [])}")
    lines.append(f"Grid Application Success: {bool(application_summary.get('success'))}")
    lines.append(f"Applied Lever Updates: {application_summary.get('applied_lever_update_count')}")
    lines.append(f"Applied Levers: {application_summary.get('applied_lever_count')}")
    lines.append(f"Accounting All OK: {accounting_check.get('all_ok')}")
    lines.append("")
    _append_realism_memo_lines(lines, controller_state)
    lines.append("")
    _append_realism_resolution_lines(lines, planning_run, controller_state)
    lines.append("")
    lines.append("GPT Narrative:")
    lines.append(str(planning_run.get("gpt_narrative") or "").strip())
    lines.append("")
    lines.append("Quarterly Summary:")
    for item in quarter_rows:
      try:
        quarter_index = int(item.get("quarter_index") or 0)
      except Exception:
        quarter_index = 0
      if quarter_index <= 0:
        continue
      lines.append(
        " | ".join(
          [
            f"Q{quarter_index}",
            f"Revenue {float(item.get('revenue') or 0.0):,.2f}",
            f"EBITDA {float(item.get('ebitda') or 0.0):,.2f}",
            f"Cash {float(item.get('ending_cash') or 0.0):,.2f}",
            f"Acct Check {float(item.get('accounting_equation_check') or 0.0):,.6f}",
          ]
        )
      )
    lines.append("")
    lines.append("Annual Summary:")
    for year_index in sorted(annual.keys()):
      lines.append(f"Year {year_index}:")
      for key in sorted(annual[year_index].keys()):
        lines.append(f"  {key}: {annual[year_index][key]:,.2f}")

    with open(path, "w", encoding="utf-8") as handle:
      handle.write("\n".join(lines).rstrip() + "\n")
    return path
  except Exception:
    return None


def _save_new_runner_grid_report(
  *,
  base_url: str,
  output_dir: str,
  seed: str,
  draft_id: Optional[str],
  written_at: Optional[datetime] = None,
) -> Optional[str]:
  try:
    os.makedirs(output_dir, exist_ok=True)
    now = written_at or _eastern_now()
    path = _build_named_artifact_path(output_dir=output_dir, seed=seed, written_at=now, suffix="quarter-grid")
    snapshot = _fetch_persisted_state_snapshot(base_url=base_url, draft_id=draft_id)
    row = (
      (((snapshot.get("payload") or {}) if isinstance(snapshot.get("payload"), dict) else {}).get("row") or {})
      if isinstance(snapshot, dict)
      else {}
    )
    if not isinstance(row, dict) or not row:
      return None
    planning_run = _parse_planning_run(row.get("planning_run_json"))
    controller_state = _parse_controller_resolution_state(
      planning_run_raw=planning_run,
      memo_raw=row.get("realism_memo_json"),
    )
    gpt_meta = planning_run.get("gpt_grid_metadata") if isinstance(planning_run.get("gpt_grid_metadata"), dict) else {}
    validation = gpt_meta.get("validation") if isinstance(gpt_meta.get("validation"), dict) else {}
    grid_rows = []
    response_payload = gpt_meta.get("response_json") if isinstance(gpt_meta.get("response_json"), dict) else {}
    legacy_grid_payload = gpt_meta.get("grid_json") if isinstance(gpt_meta.get("grid_json"), dict) else {}
    rows_payload = response_payload or legacy_grid_payload
    if isinstance(rows_payload, dict):
      grid_rows = [item for item in (rows_payload.get("rows") or []) if isinstance(item, dict)]

    lines: List[str] = []
    lines.append(f"Business Name: {str(row.get('business_name') or '').strip()}")
    lines.append(f"Draft ID: {str(draft_id or row.get('draft_id') or '').strip()}")
    lines.append(f"Planning Mode: {str(planning_run.get('planning_mode') or '').strip()}")
    lines.append(f"Prompt File: {str(planning_run.get('prompt_file') or '').strip()}")
    lines.append(f"Requested Rows: {gpt_meta.get('requested_row_count')}")
    lines.append(f"Returned Rows: {gpt_meta.get('returned_row_count')}")
    lines.append(f"Batch Count: {gpt_meta.get('batch_count')}")
    lines.append(f"Runtime Seconds: {gpt_meta.get('runtime_seconds')}")
    lines.append(f"Missing Rows: {len(validation.get('missing_rows') or [])}")
    lines.append(f"Extra Rows: {len(validation.get('extra_rows') or [])}")
    lines.append(f"Malformed Rows: {len(validation.get('malformed_rows') or [])}")
    lines.append(f"Duplicate Rows: {len(validation.get('duplicate_rows') or [])}")
    lines.append("")
    _append_realism_memo_lines(lines, controller_state)
    lines.append("")
    lines.append("GPT Narrative:")
    lines.append(str(planning_run.get("gpt_narrative") or "").strip())
    lines.append("")
    lines.append("Grid Rows:")
    for item in grid_rows:
      row_id = str(item.get("row_id") or "").strip()
      row_type = str(item.get("row_type") or "").strip()
      lines.append(f"{row_id} [{row_type}]")
      quarter_values = [entry for entry in (item.get("quarter_values") or []) if isinstance(entry, dict)]
      for entry in quarter_values:
        lines.append(
          f"  Q{int(entry.get('quarter_index') or 0)}: {float(entry.get('value') or 0.0):,.6f}"
        )
      lines.append("")

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
      base_url=base_url,
      output_dir=output_dir,
      seed=artifact_seed,
      bootstrap=bootstrap,
      transcript=transcript,
      draft_id=draft_id,
      client_id=client_id,
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
    new_runner_path = _save_new_runner_report(
      base_url=base_url,
      output_dir=DEFAULT_NEW_RUNNER_DIR,
      seed=artifact_seed,
      bootstrap=bootstrap,
      draft_id=draft_id,
      written_at=written_at,
    )
    if new_runner_path:
      print(f"Saved New Runner report: {new_runner_path}")
    new_runner_grid_path = _save_new_runner_grid_report(
      base_url=base_url,
      output_dir=DEFAULT_NEW_RUNNER_DIR,
      seed=artifact_seed,
      draft_id=draft_id,
      written_at=written_at,
    )
    if new_runner_grid_path:
      print(f"Saved New Runner grid report: {new_runner_grid_path}")
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
      "X-Planning-Trace-Run-Name": trace_file_name,
      "X-Planning-Trace-Reset": "1",
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
        system_run_started = time.perf_counter()
        system_run_response = _post_json(
          f"{base_url}/api/intake-consult/system-run",
          {
            "draft_id": draft_id,
            "client_id": client_id,
          },
          timeout=None,
          headers=trace_headers,
        )
        system_run_ms = int(round((time.perf_counter() - system_run_started) * 1000.0))
        system_message = str(system_run_response.get("assistant_message") or "").strip() or "System run complete."
        transcript.append({"role": "assistant", "content": system_message, "focus": "system"})
        print(system_message)
        draft = _get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
        realism_flags = _realism_final_flags_from_draft(draft)
        print(
          "Final flags:",
          json.dumps(
            {
              "ops_confirmed": draft.get("ops_confirmed"),
              "market_confirmed": draft.get("market_confirmed"),
              "people_confirmed": draft.get("people_confirmed"),
              "financials_confirmed": draft.get("financials_confirmed"),
              **realism_flags,
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
          app_response_ms=system_run_ms,
          assistant_chars=len(assistant_message),
          user_chars=0,
          stop_flag=True,
          stop_reason="system run complete",
        )
        _finish_metrics(status="completed", stop_reason="system run complete", total_turns=turn_index + 1)
        _persist_report(status="completed", stop_reason="system run complete")
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
        headers={"X-Planning-Trace-Run-Name": trace_file_name},
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
