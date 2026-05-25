"""``post_intake_run_diagnostics`` table — P3.33 Phase 3 step 9a.

One row per event in the post-intake pipeline. Phase 4 verification
scenarios + production debugging both read these rows to know exactly
what happened at every juncture.

Schema (per step 9 directive):
  id              BIGINT AUTO_INCREMENT PRIMARY KEY
  draft_id        VARCHAR(64) NOT NULL
  planning_run_id VARCHAR(64) NOT NULL
  phase           VARCHAR(64) NOT NULL    -- PhaseCode value
  event_code      VARCHAR(128) NOT NULL   -- EventCode value
  status          VARCHAR(16) NOT NULL    -- Status value
  diagnostic_data JSON                    -- free-form payload
  latency_ms      INT NULL
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP

Indices:
  ix_draft_run (draft_id, planning_run_id)
  ix_phase_event (phase, event_code)
  ix_created_at (created_at)

``emit_diagnostic`` is the only sanctioned writer. It validates the
(phase, event_code) pair against EVENT_CODES_BY_PHASE; mismatches
raise ValueError (these are caller bugs).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (
  EventCode,
  PhaseCode,
  Status,
  event_code_belongs_to_phase,
)


RUN_DIAGNOSTICS_TABLE_NAME = "post_intake_run_diagnostics"

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {RUN_DIAGNOSTICS_TABLE_NAME} (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  draft_id        VARCHAR(64)  NOT NULL,
  planning_run_id VARCHAR(64)  NOT NULL,
  phase           VARCHAR(64)  NOT NULL,
  event_code      VARCHAR(128) NOT NULL,
  status          VARCHAR(16)  NOT NULL,
  diagnostic_data JSON         NULL,
  latency_ms      INT          NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_draft_run    (draft_id, planning_run_id),
  KEY ix_phase_event  (phase, event_code),
  KEY ix_created_at   (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

def ensure_run_diagnostics_table(conn) -> None:
  """Idempotently create ``post_intake_run_diagnostics``. Mirrors the
  ensure-table convention used elsewhere in post_intake_* modules."""
  if conn is None:
    return
  cur = conn.cursor()
  try:
    cur.execute(_CREATE_TABLE_SQL)
    try:
      conn.commit()
    except Exception:
      pass
  finally:
    try:
      cur.close()
    except Exception:
      pass


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------

def _coerce_enum(value: Any, enum_cls):
  if value is None:
    return None
  if isinstance(value, enum_cls):
    return value
  try:
    return enum_cls(value)
  except Exception:
    try:
      return enum_cls[value]
    except Exception:
      return None


def _str_or_none(value: Any) -> Optional[str]:
  if value is None:
    return None
  s = str(value).strip()
  return s or None


def _json_or_none(value: Any) -> Optional[str]:
  if value is None:
    return None
  if isinstance(value, str):
    return value
  try:
    return json.dumps(value, default=str, sort_keys=True)
  except Exception:
    return json.dumps({"_repr": repr(value)[:1000]})


def _int_or_none(value: Any) -> Optional[int]:
  if value is None:
    return None
  try:
    return int(value)
  except (TypeError, ValueError):
    return None


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def emit_diagnostic(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  phase: Union[PhaseCode, str],
  event_code: Union[EventCode, str],
  status: Union[Status, str] = Status.COMPLETED,
  diagnostic_data: Optional[Dict[str, Any]] = None,
  latency_ms: Optional[int] = None,
  ensure_table: bool = True,
) -> Optional[int]:
  """Insert one row into ``post_intake_run_diagnostics``.

  Returns the new row id on success, ``None`` if ``conn`` is None.

  Validation:
    - (phase, event_code) must be a registered pair per
      EVENT_CODES_BY_PHASE; mismatches raise ValueError.
    - draft_id + planning_run_id are required.
    - Unknown enum values raise ValueError.

  ``diagnostic_data`` is JSON-serialized via json.dumps with a
  default=str fallback for non-serializable values. ``latency_ms`` is
  optional; phases that measure latency emit a paired
  started/completed row and the caller computes elapsed time.
  """
  phase_enum = _coerce_enum(phase, PhaseCode)
  event_enum = _coerce_enum(event_code, EventCode)
  status_enum = _coerce_enum(status, Status)

  if phase_enum is None:
    raise ValueError(f"unknown phase: {phase!r}")
  if event_enum is None:
    raise ValueError(f"unknown event_code: {event_code!r}")
  if status_enum is None:
    raise ValueError(f"unknown status: {status!r}")
  if not event_code_belongs_to_phase(event_enum, phase_enum):
    raise ValueError(
      f"event_code {event_enum.value!r} is not registered for "
      f"phase {phase_enum.value!r} (see EVENT_CODES_BY_PHASE)"
    )

  draft_id_clean = _str_or_none(draft_id)
  planning_run_id_clean = _str_or_none(planning_run_id)
  if not draft_id_clean or not planning_run_id_clean:
    raise ValueError("draft_id and planning_run_id are required")

  data_json = _json_or_none(diagnostic_data)
  latency = _int_or_none(latency_ms)

  if conn is None:
    return None

  if ensure_table:
    ensure_run_diagnostics_table(conn)

  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      INSERT INTO {RUN_DIAGNOSTICS_TABLE_NAME}
        (draft_id, planning_run_id, phase, event_code, status,
         diagnostic_data, latency_ms)
      VALUES (%s, %s, %s, %s, %s, %s, %s)
      """,
      (
        draft_id_clean, planning_run_id_clean,
        phase_enum.value, event_enum.value, status_enum.value,
        data_json, latency,
      ),
    )
    row_id = cur.lastrowid
    try:
      conn.commit()
    except Exception:
      pass
    return int(row_id) if row_id is not None else None
  finally:
    try:
      cur.close()
    except Exception:
      pass


# ---------------------------------------------------------------------------
# Fetch helper — Phase 4 verification + dev debugging.
# ---------------------------------------------------------------------------

def fetch_diagnostics(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  phase: Optional[Union[PhaseCode, str]] = None,
  event_code: Optional[Union[EventCode, str]] = None,
  status: Optional[Union[Status, str]] = None,
) -> List[Dict[str, Any]]:
  """Return diagnostic rows for the (draft_id, planning_run_id) pair,
  ordered by id ASC. Optional filters narrow the result set."""
  if conn is None:
    return []

  where: List[str] = ["draft_id=%s", "planning_run_id=%s"]
  params: List[Any] = [draft_id, planning_run_id]

  if phase is not None:
    p = _coerce_enum(phase, PhaseCode)
    where.append("phase=%s")
    params.append(p.value if p is not None else str(phase))
  if event_code is not None:
    e = _coerce_enum(event_code, EventCode)
    where.append("event_code=%s")
    params.append(e.value if e is not None else str(event_code))
  if status is not None:
    s = _coerce_enum(status, Status)
    where.append("status=%s")
    params.append(s.value if s is not None else str(status))

  sql = (
    f"SELECT * FROM {RUN_DIAGNOSTICS_TABLE_NAME} "
    f"WHERE {' AND '.join(where)} ORDER BY id ASC"
  )

  try:
    cur = conn.cursor(dictionary=True)
  except TypeError:
    cur = conn.cursor()
  try:
    cur.execute(sql, tuple(params))
    rows = cur.fetchall() or []
    return list(rows)
  finally:
    try:
      cur.close()
    except Exception:
      pass


__all__ = [
  "RUN_DIAGNOSTICS_TABLE_NAME",
  "ensure_run_diagnostics_table",
  "emit_diagnostic",
  "fetch_diagnostics",
]
