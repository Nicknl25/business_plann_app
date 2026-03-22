from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


def _utc_now_str() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

def _table_columns(conn, table_name: str) -> Set[str]:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      SELECT COLUMN_NAME
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
  out: Set[str] = set()
  for r in rows:
    try:
      out.add(str(r[0]))
    except Exception:
      continue
  return out

def _normalize_flat_value(value: Any) -> Any:
  if isinstance(value, (dict, list)):
    return json.dumps(value, ensure_ascii=False)
  return value


_ENGINE_JSON_COLUMNS = (
  "normalized_traits_json",
  "benchmark_payload_json",
  "constraint_engine_state_json",
  "forecast_engine_state_json",
  "forecast_quarters_json",
  "engine_versions_json",
)


def ensure_table(conn) -> None:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      CREATE TABLE IF NOT EXISTS intake_consult_drafts (
        draft_id CHAR(32) NOT NULL PRIMARY KEY,
        client_id CHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
        active_focus VARCHAR(20) NOT NULL DEFAULT 'ops',
        ops_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        market_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        people_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        financials_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        consistency_passed TINYINT(1) NOT NULL DEFAULT 0,
        business_name VARCHAR(255) NULL,
        business_address LONGTEXT NULL,
        address_street VARCHAR(255) NULL,
        address_city VARCHAR(255) NULL,
        address_state VARCHAR(255) NULL,
        address_zip VARCHAR(50) NULL,
        address_country VARCHAR(255) NULL,
        business_start_date VARCHAR(50) NULL,
        messages_json LONGTEXT NULL,
        operating_model_json LONGTEXT NULL,
        target_market_json LONGTEXT NULL,
        people_json LONGTEXT NULL,
        financials_json LONGTEXT NULL,
        marketing_model_json LONGTEXT NULL,
        financials_year1_json LONGTEXT NULL,
        normalized_traits_json LONGTEXT NULL,
        benchmark_payload_json LONGTEXT NULL,
        constraint_engine_state_json LONGTEXT NULL,
        forecast_engine_state_json LONGTEXT NULL,
        forecast_quarters_json LONGTEXT NULL,
        engine_versions_json LONGTEXT NULL,
        pending_ops_milestone_json LONGTEXT NULL,
        fulfillment_json JSON NULL,
        ops_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        market_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        people_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        financials_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        completed_at DATETIME(6) NULL,
        submitted_at DATETIME(6) NULL,
        intake_submission_id BIGINT UNSIGNED NULL,
        UNIQUE KEY uniq_client_id (client_id),
        KEY idx_status (status),
        KEY idx_active_focus (active_focus),
        KEY idx_updated_at (updated_at)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
      """
    )
  finally:
    try:
      cur.close()
    except Exception:
      pass

  # Older deployments may have created the table without newer columns.
  cols = _table_columns(conn, "intake_consult_drafts")
  alterations: list[str] = []
  if "active_focus" not in cols:
    alterations.append("ADD COLUMN active_focus VARCHAR(20) NOT NULL DEFAULT 'ops'")
  if "ops_confirmed" not in cols:
    alterations.append("ADD COLUMN ops_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "market_confirmed" not in cols:
    alterations.append("ADD COLUMN market_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "people_confirmed" not in cols:
    alterations.append("ADD COLUMN people_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "financials_confirmed" not in cols:
    alterations.append("ADD COLUMN financials_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "consistency_passed" not in cols:
    alterations.append("ADD COLUMN consistency_passed TINYINT(1) NOT NULL DEFAULT 0")
  if "business_name" not in cols:
    alterations.append("ADD COLUMN business_name VARCHAR(255) NULL")
  if "business_address" not in cols:
    alterations.append("ADD COLUMN business_address LONGTEXT NULL")
  if "address_street" not in cols:
    alterations.append("ADD COLUMN address_street VARCHAR(255) NULL")
  if "address_city" not in cols:
    alterations.append("ADD COLUMN address_city VARCHAR(255) NULL")
  if "address_state" not in cols:
    alterations.append("ADD COLUMN address_state VARCHAR(255) NULL")
  if "address_zip" not in cols:
    alterations.append("ADD COLUMN address_zip VARCHAR(50) NULL")
  if "address_country" not in cols:
    alterations.append("ADD COLUMN address_country VARCHAR(255) NULL")
  if "business_start_date" not in cols:
    alterations.append("ADD COLUMN business_start_date VARCHAR(50) NULL")
  if "target_market_json" not in cols:
    alterations.append("ADD COLUMN target_market_json LONGTEXT NULL")
  if "people_json" not in cols:
    alterations.append("ADD COLUMN people_json LONGTEXT NULL")
  if "financials_json" not in cols:
    alterations.append("ADD COLUMN financials_json LONGTEXT NULL")
  if "marketing_model_json" not in cols:
    alterations.append("ADD COLUMN marketing_model_json LONGTEXT NULL")
  if "financials_year1_json" not in cols:
    alterations.append("ADD COLUMN financials_year1_json LONGTEXT NULL")
  if "normalized_traits_json" not in cols:
    alterations.append("ADD COLUMN normalized_traits_json LONGTEXT NULL")
  if "benchmark_payload_json" not in cols:
    alterations.append("ADD COLUMN benchmark_payload_json LONGTEXT NULL")
  if "constraint_engine_state_json" not in cols:
    alterations.append("ADD COLUMN constraint_engine_state_json LONGTEXT NULL")
  if "forecast_engine_state_json" not in cols:
    alterations.append("ADD COLUMN forecast_engine_state_json LONGTEXT NULL")
  if "forecast_quarters_json" not in cols:
    alterations.append("ADD COLUMN forecast_quarters_json LONGTEXT NULL")
  if "engine_versions_json" not in cols:
    alterations.append("ADD COLUMN engine_versions_json LONGTEXT NULL")
  if "pending_ops_milestone_json" not in cols:
    alterations.append("ADD COLUMN pending_ops_milestone_json LONGTEXT NULL")
  if "fulfillment_json" not in cols:
    alterations.append("ADD COLUMN fulfillment_json JSON NULL")
  if "ops_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN ops_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")
  if "market_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN market_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")
  if "people_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN people_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")
  if "financials_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN financials_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")

  if alterations:
    cur2 = conn.cursor()
    try:
      for alter in alterations:
        cur2.execute(f"ALTER TABLE intake_consult_drafts {alter}")
      conn.commit()
    except Exception:
      # Best-effort: ignore if ALTER fails due to permissions or race.
      try:
        conn.rollback()
      except Exception:
        pass
    finally:
      try:
        cur2.close()
      except Exception:
        pass


def create_draft(conn, *, client_id: str) -> Dict[str, Any]:
  ensure_table(conn)
  draft_id = uuid.uuid4().hex
  now = _utc_now_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      INSERT INTO intake_consult_drafts
        (draft_id, client_id, status, messages_json, created_at, updated_at)
      VALUES
        (%s, %s, 'in_progress', %s, %s, %s)
      """,
      (draft_id, client_id, json.dumps([], ensure_ascii=False), now, now),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return {"draft_id": draft_id, "client_id": client_id, "status": "in_progress"}


def get_draft(conn, *, draft_id: str) -> Dict[str, Any]:
  ensure_table(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT * FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1",
      (draft_id,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not row or not isinstance(row, dict):
    raise RuntimeError(f"Consult draft not found for draft_id={draft_id!r}")
  return row


def _parse_messages(raw: Any) -> List[Dict[str, str]]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return [m for m in raw if isinstance(m, dict)]
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  if isinstance(parsed, list):
    return [m for m in parsed if isinstance(m, dict)]
  return []


def _parse_json_object(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _render_messages_for_storage(
  *,
  row: Dict[str, Any],
  messages: List[Dict[str, str]],
  operating_model_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  normalized_traits_json: Optional[Dict[str, Any]] = None,
  benchmark_payload_json: Optional[Dict[str, Any]] = None,
  constraint_engine_state_json: Optional[Dict[str, Any]] = None,
  forecast_engine_state_json: Optional[Dict[str, Any]] = None,
  forecast_quarters_json: Optional[List[Dict[str, Any]]] = None,
  engine_versions_json: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
  try:
    from fact_templates import render_fact_template, sanitize_fact_template  # type: ignore
  except Exception:
    return messages

  latest_business_facts: Dict[str, Any] = {
    "name": row.get("business_name"),
    "address": row.get("business_address"),
    "address_street": row.get("address_street"),
    "address_city": row.get("address_city"),
    "address_state": row.get("address_state"),
    "address_zip": row.get("address_zip"),
    "address_country": row.get("address_country"),
    "start_date": row.get("business_start_date"),
  }
  if isinstance(business_facts, dict):
    for key, value in business_facts.items():
      if key in latest_business_facts:
        latest_business_facts[key] = value

  shared_context: Dict[str, Any] = {
    "operating_model": operating_model_json if operating_model_json is not None else _parse_json_object(row.get("operating_model_json")),
    "target_market": target_market_json if target_market_json is not None else _parse_json_object(row.get("target_market_json")),
    "people_capability": people_json if people_json is not None else _parse_json_object(row.get("people_json")),
    "financials": financials_json if financials_json is not None else _parse_json_object(row.get("financials_json")),
    "marketing": marketing_model_json if marketing_model_json is not None else _parse_json_object(row.get("marketing_model_json")),
    "financials_year1_json": (
      financials_year1_json if financials_year1_json is not None else _parse_json_object(row.get("financials_year1_json"))
    ),
    "normalized_traits": (
      normalized_traits_json if normalized_traits_json is not None else _parse_json_object(row.get("normalized_traits_json"))
    ),
    "benchmark_payload": (
      benchmark_payload_json if benchmark_payload_json is not None else _parse_json_object(row.get("benchmark_payload_json"))
    ),
    "constraint_engine_state": (
      constraint_engine_state_json
      if constraint_engine_state_json is not None
      else _parse_json_object(row.get("constraint_engine_state_json"))
    ),
    "consistency_solver_state": _parse_json_object(
      (_parse_json_object(row.get("financials_json")) or {}).get("_consistency_solver_state")
    ),
    "forecast_engine_state": (
      forecast_engine_state_json
      if forecast_engine_state_json is not None
      else _parse_json_object(row.get("forecast_engine_state_json"))
    ),
    "engine_versions": (
      engine_versions_json if engine_versions_json is not None else _parse_json_object(row.get("engine_versions_json"))
    ),
  }

  rendered_messages: List[Dict[str, str]] = []
  for message in messages:
    if not isinstance(message, dict):
      continue
    role = str(message.get("role") or "").strip()
    content = str(message.get("content") or "")
    rendered = content
    if role == "assistant" and content:
      try:
        rendered = render_fact_template(
          content,
          shared_context=shared_context,
          business_facts=latest_business_facts,
        )
      except Exception:
        rendered = content
      rendered = sanitize_fact_template(str(rendered or ""))
    rendered_message = dict(message)
    rendered_message["content"] = rendered
    rendered_messages.append(rendered_message)
  return rendered_messages


def append_messages(
  conn,
  *,
  draft_id: str,
  new_messages: List[Dict[str, str]],
  status: Optional[str] = None,
  operating_model_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  normalized_traits_json: Optional[Dict[str, Any]] = None,
  benchmark_payload_json: Optional[Dict[str, Any]] = None,
  constraint_engine_state_json: Optional[Dict[str, Any]] = None,
  forecast_engine_state_json: Optional[Dict[str, Any]] = None,
  forecast_quarters_json: Optional[List[Dict[str, Any]]] = None,
  engine_versions_json: Optional[Dict[str, Any]] = None,
  pending_ops_milestone_json: Optional[Any] = None,
  fulfillment_json: Optional[Dict[str, Any]] = None,
  active_focus: Optional[str] = None,
  confirmations: Optional[Dict[str, bool]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  consistency_passed: Optional[bool] = None,
  flat_fields: Optional[Dict[str, Any]] = None,
  completed: bool = False,
) -> Dict[str, Any]:
  row = get_draft(conn, draft_id=draft_id)
  messages = _parse_messages(row.get("messages_json"))
  messages.extend(new_messages)
  messages = _render_messages_for_storage(
    row=row,
    messages=messages,
    operating_model_json=operating_model_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    marketing_model_json=marketing_model_json,
    financials_year1_json=financials_year1_json,
    normalized_traits_json=normalized_traits_json,
    benchmark_payload_json=benchmark_payload_json,
    constraint_engine_state_json=constraint_engine_state_json,
    forecast_engine_state_json=forecast_engine_state_json,
    forecast_quarters_json=forecast_quarters_json,
    engine_versions_json=engine_versions_json,
    business_facts=business_facts,
  )

  now = _utc_now_str()
  set_parts = ["messages_json = %s", "updated_at = %s"]
  values: List[Any] = [json.dumps(messages, ensure_ascii=False), now]

  if status:
    set_parts.append("status = %s")
    values.append(status)
    # If we are reopening a previously completed consult (e.g. an edit after the
    # consistency check), clear completed_at so the UI does not treat it as
    # "done" while the model is being refined.
    if str(status).strip().lower() == "in_progress":
      set_parts.append("completed_at = NULL")

  if operating_model_json is not None:
    set_parts.append("operating_model_json = %s")
    values.append(json.dumps(operating_model_json, ensure_ascii=False))

  if target_market_json is not None:
    set_parts.append("target_market_json = %s")
    values.append(json.dumps(target_market_json, ensure_ascii=False))

  if people_json is not None:
    set_parts.append("people_json = %s")
    values.append(json.dumps(people_json, ensure_ascii=False))

  if financials_json is not None:
    set_parts.append("financials_json = %s")
    values.append(json.dumps(financials_json, ensure_ascii=False))

  if marketing_model_json is not None:
    set_parts.append("marketing_model_json = %s")
    values.append(json.dumps(marketing_model_json, ensure_ascii=False))

  if financials_year1_json is not None:
    set_parts.append("financials_year1_json = %s")
    values.append(json.dumps(financials_year1_json, ensure_ascii=False))

  if normalized_traits_json is not None:
    set_parts.append("normalized_traits_json = %s")
    values.append(json.dumps(normalized_traits_json, ensure_ascii=False))

  if benchmark_payload_json is not None:
    set_parts.append("benchmark_payload_json = %s")
    values.append(json.dumps(benchmark_payload_json, ensure_ascii=False))

  if constraint_engine_state_json is not None:
    set_parts.append("constraint_engine_state_json = %s")
    values.append(json.dumps(constraint_engine_state_json, ensure_ascii=False))

  if forecast_engine_state_json is not None:
    set_parts.append("forecast_engine_state_json = %s")
    values.append(json.dumps(forecast_engine_state_json, ensure_ascii=False))

  if forecast_quarters_json is not None:
    set_parts.append("forecast_quarters_json = %s")
    values.append(json.dumps(forecast_quarters_json, ensure_ascii=False))

  if engine_versions_json is not None:
    set_parts.append("engine_versions_json = %s")
    values.append(json.dumps(engine_versions_json, ensure_ascii=False))

  if pending_ops_milestone_json is not None:
    set_parts.append("pending_ops_milestone_json = %s")
    values.append(json.dumps(pending_ops_milestone_json, ensure_ascii=False))

  if fulfillment_json is not None:
    set_parts.append("fulfillment_json = %s")
    values.append(json.dumps(fulfillment_json, ensure_ascii=False))

  if active_focus is not None:
    set_parts.append("active_focus = %s")
    values.append(str(active_focus).strip() or "ops")

  if confirmations:
    for key, col in (
      ("ops", "ops_confirmed"),
      ("market", "market_confirmed"),
      ("people", "people_confirmed"),
      ("financials", "financials_confirmed"),
    ):
      if key in confirmations:
        set_parts.append(f"{col} = %s")
        values.append(1 if confirmations[key] else 0)

  if business_facts:
    if "name" in business_facts:
      set_parts.append("business_name = %s")
      values.append(str(business_facts.get("name") or "").strip() or None)
    if "address" in business_facts:
      set_parts.append("business_address = %s")
      values.append(str(business_facts.get("address") or "").strip() or None)
    if "address_street" in business_facts:
      set_parts.append("address_street = %s")
      values.append(str(business_facts.get("address_street") or "").strip() or None)
    if "address_city" in business_facts:
      set_parts.append("address_city = %s")
      values.append(str(business_facts.get("address_city") or "").strip() or None)
    if "address_state" in business_facts:
      set_parts.append("address_state = %s")
      values.append(str(business_facts.get("address_state") or "").strip() or None)
    if "address_zip" in business_facts:
      set_parts.append("address_zip = %s")
      values.append(str(business_facts.get("address_zip") or "").strip() or None)
    if "address_country" in business_facts:
      set_parts.append("address_country = %s")
      values.append(str(business_facts.get("address_country") or "").strip() or None)
    if "start_date" in business_facts:
      set_parts.append("business_start_date = %s")
      values.append(str(business_facts.get("start_date") or "").strip() or None)

  if consistency_passed is not None:
    set_parts.append("consistency_passed = %s")
    values.append(1 if consistency_passed else 0)

  if flat_fields:
    reserved = {
      "draft_id",
      "client_id",
      "status",
      "active_focus",
      "ops_confirmed",
      "market_confirmed",
      "people_confirmed",
      "financials_confirmed",
      "consistency_passed",
      "business_name",
      "business_address",
      "address_street",
      "address_city",
      "address_state",
      "address_zip",
      "address_country",
      "business_start_date",
      "messages_json",
      "operating_model_json",
      "target_market_json",
      "people_json",
      "financials_json",
      "marketing_model_json",
      "financials_year1_json",
      "normalized_traits_json",
      "benchmark_payload_json",
      "constraint_engine_state_json",
      "forecast_engine_state_json",
      "forecast_quarters_json",
      "engine_versions_json",
      "pending_ops_milestone_json",
      "fulfillment_json",
      "created_at",
      "updated_at",
      "completed_at",
      "submitted_at",
      "intake_submission_id",
    }
    cols = _table_columns(conn, "intake_consult_drafts")
    for key, raw_val in flat_fields.items():
      if key in reserved:
        continue
      if key not in cols:
        continue
      set_parts.append(f"`{key}` = %s")
      values.append(_normalize_flat_value(raw_val))

  if completed:
    set_parts.append("completed_at = %s")
    values.append(now)

  values.append(draft_id)
  sql = "UPDATE intake_consult_drafts SET " + ", ".join(set_parts) + " WHERE draft_id = %s"

  cur = conn.cursor()
  try:
    cur.execute(sql, values)
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass

  return {"draft_id": draft_id, "client_id": row.get("client_id"), "messages": messages}


def mark_submitted(
  conn,
  *,
  draft_id: str,
  intake_submission_id: int,
) -> None:
  now = _utc_now_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      UPDATE intake_consult_drafts
      SET status = 'submitted',
          submitted_at = %s,
          intake_submission_id = %s,
          updated_at = %s
      WHERE draft_id = %s
        AND (intake_submission_id IS NULL)
      """,
      (now, int(intake_submission_id), now, draft_id),
    )
    if getattr(cur, "rowcount", 0) == 0:
      raise RuntimeError("Draft already submitted or missing.")
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def reopen_draft(conn, *, draft_id: str) -> None:
  """
  Reopen a completed consult for continued conversation and refinement.
  Keeps messages_json intact but clears operating_model_json and completed_at.
  """
  ensure_table(conn)
  now = _utc_now_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      UPDATE intake_consult_drafts
      SET status = 'in_progress',
          operating_model_json = NULL,
          completed_at = NULL,
          updated_at = %s
      WHERE draft_id = %s
        AND status = 'completed'
      """,
      (now, draft_id),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
