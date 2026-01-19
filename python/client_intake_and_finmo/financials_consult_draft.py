from __future__ import annotations

import json
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
      CREATE TABLE IF NOT EXISTS intake_financials_drafts (
        draft_id CHAR(32) NOT NULL PRIMARY KEY,
        client_id CHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
        messages_json LONGTEXT NULL,
        financials_json LONGTEXT NULL,
        financials_year1_json LONGTEXT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        completed_at DATETIME(6) NULL,
        KEY idx_status (status),
        KEY idx_updated_at (updated_at)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
      """
    )
  finally:
    try:
      cur.close()
    except Exception:
      pass

  cols = _table_columns(conn, "intake_financials_drafts")
  alterations: list[str] = []
  if "financials_year1_json" not in cols:
    alterations.append("ADD COLUMN financials_year1_json LONGTEXT NULL")

  if alterations:
    cur2 = conn.cursor()
    try:
      for alter in alterations:
        cur2.execute(f"ALTER TABLE intake_financials_drafts {alter}")
      conn.commit()
    except Exception:
      try:
        conn.rollback()
      except Exception:
        pass
    finally:
      try:
        cur2.close()
      except Exception:
        pass


def create_draft(conn, *, draft_id: str, client_id: str) -> Dict[str, Any]:
  ensure_table(conn)
  now = _utc_now_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      INSERT INTO intake_financials_drafts
        (draft_id, client_id, status, messages_json, created_at, updated_at)
      VALUES
        (%s, %s, 'in_progress', %s, %s, %s)
      ON DUPLICATE KEY UPDATE
        updated_at = VALUES(updated_at)
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
      "SELECT * FROM intake_financials_drafts WHERE draft_id = %s LIMIT 1",
      (draft_id,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not row or not isinstance(row, dict):
    raise RuntimeError(f"Financials draft not found for draft_id={draft_id!r}")
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
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
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

  if financials_json is not None:
    set_parts.append("financials_json = %s")
    values.append(json.dumps(financials_json, ensure_ascii=False))

  if financials_year1_json is not None:
    set_parts.append("financials_year1_json = %s")
    values.append(json.dumps(financials_year1_json, ensure_ascii=False))

  if flat_fields:
    reserved = {
      "draft_id",
      "client_id",
      "status",
      "messages_json",
      "financials_json",
      "financials_year1_json",
      "created_at",
      "updated_at",
      "completed_at",
    }
    cols = _table_columns(conn, "intake_financials_drafts")
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
  sql = (
    "UPDATE intake_financials_drafts SET "
    + ", ".join(set_parts)
    + " WHERE draft_id = %s"
  )

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


def reopen_draft(conn, *, draft_id: str) -> None:
  """
  Reopen a completed draft for continued conversation and refinement.
  Keeps messages_json intact but clears the finalized JSON and completed_at.
  """
  ensure_table(conn)
  now = _utc_now_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      UPDATE intake_financials_drafts
      SET status = 'in_progress',
          financials_json = NULL,
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
