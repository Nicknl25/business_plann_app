from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence

from intake_submission import generate_client_id


def _table_columns(conn, table: str) -> List[str]:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      SELECT COLUMN_NAME
      FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = %s
      """,
      (table,),
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  columns: List[str] = []
  for row in rows:
    if isinstance(row, dict):
      name = row.get("COLUMN_NAME")
    else:
      name = row[0] if row else None
    if name:
      columns.append(str(name))
  return columns


def _fetchone_dict(cur) -> Optional[Dict[str, Any]]:
  row = cur.fetchone()
  if row is None:
    return None
  if isinstance(row, dict):
    return dict(row)
  desc = cur.description or []
  mapped: Dict[str, Any] = {}
  for idx, col in enumerate(desc):
    key = str(col[0])
    mapped[key] = row[idx] if isinstance(row, (list, tuple)) and idx < len(row) else None
  return mapped


def _json_dump(value: Any) -> Any:
  if isinstance(value, (dict, list)):
    return json.dumps(value, ensure_ascii=True)
  return value


def create_draft(conn, *, client_id: Optional[str] = None) -> Dict[str, Any]:
  draft_id = uuid.uuid4().hex
  client_id = client_id or generate_client_id()
  columns = set(_table_columns(conn, "intake_consult_drafts"))
  if not columns:
    raise RuntimeError("intake_consult_drafts has no columns visible to the current user.")

  updates: Dict[str, Any] = {}
  for key, value in (
    ("draft_id", draft_id),
    ("client_id", client_id),
    ("status", "draft"),
    ("draft_status", "draft"),
    ("messages_json", json.dumps([])),
    ("interaction_mode", "chat"),
  ):
    if key in columns:
      updates[key] = value

  col_names = list(updates.keys())
  placeholders = ", ".join(["%s"] * len(col_names))
  values = [_json_dump(updates[col]) for col in col_names]

  cur = conn.cursor()
  try:
    cur.execute(
      f"INSERT INTO intake_consult_drafts ({', '.join(col_names)}) VALUES ({placeholders})",
      values,
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass

  return get_draft(conn, draft_id=draft_id) or {"draft_id": draft_id, "client_id": client_id}


def get_draft(conn, *, draft_id: str) -> Dict[str, Any]:
  cur = conn.cursor()
  try:
    cur.execute(
      "SELECT * FROM intake_consult_drafts WHERE draft_id = %s",
      (str(draft_id).strip(),),
    )
    row = _fetchone_dict(cur)
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return row or {}


def update_draft(conn, *, draft_id: str, updates: Dict[str, Any]) -> None:
  if not updates:
    return
  columns = set(_table_columns(conn, "intake_consult_drafts"))
  if not columns:
    return
  filtered = {k: v for k, v in updates.items() if k in columns}
  if not filtered:
    return

  assignments = ", ".join([f"{k} = %s" for k in filtered.keys()])
  values = [_json_dump(filtered[k]) for k in filtered.keys()]
  values.append(str(draft_id).strip())

  cur = conn.cursor()
  try:
    cur.execute(
      f"UPDATE intake_consult_drafts SET {assignments} WHERE draft_id = %s",
      values,
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _parse_messages(raw: Any) -> List[Dict[str, Any]]:
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
  new_messages: Sequence[Dict[str, Any]],
  **extra_updates: Any,
) -> None:
  draft = get_draft(conn, draft_id=str(draft_id).strip())
  existing = _parse_messages(draft.get("messages_json"))
  for msg in new_messages:
    if not isinstance(msg, dict):
      continue
    role = str(msg.get("role") or "").strip()
    content = str(msg.get("content") or "")
    if not role:
      continue
    existing.append({"role": role, "content": content})

  updates: Dict[str, Any] = {"messages_json": json.dumps(existing, ensure_ascii=True)}
  updates.update(extra_updates)
  update_draft(conn, draft_id=str(draft_id).strip(), updates=updates)
