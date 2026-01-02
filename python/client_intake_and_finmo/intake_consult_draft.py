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
        business_start_date VARCHAR(50) NULL,
        messages_json LONGTEXT NULL,
        operating_model_json LONGTEXT NULL,
        target_market_json LONGTEXT NULL,
        people_json LONGTEXT NULL,
        financials_json LONGTEXT NULL,
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
  if "business_start_date" not in cols:
    alterations.append("ADD COLUMN business_start_date VARCHAR(50) NULL")
  if "target_market_json" not in cols:
    alterations.append("ADD COLUMN target_market_json LONGTEXT NULL")
  if "people_json" not in cols:
    alterations.append("ADD COLUMN people_json LONGTEXT NULL")
  if "financials_json" not in cols:
    alterations.append("ADD COLUMN financials_json LONGTEXT NULL")

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
      "business_start_date",
      "messages_json",
      "operating_model_json",
      "target_market_json",
      "people_json",
      "financials_json",
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
