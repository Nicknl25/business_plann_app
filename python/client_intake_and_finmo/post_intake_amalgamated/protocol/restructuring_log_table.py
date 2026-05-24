"""``post_intake_restructuring_log`` table — spec §10.

Per-row audit of every restructure event the cascade emits. The protocol's
guarantee (spec §10.4) is that every attempt — confirmed, vetoed, applied,
floor-built, primitive-applied, budget-aware auto-confirm — gets a row. Even
vetoes are logged with ``applied_value = NULL`` and the veto reason. The row
writer in this module is the only sanctioned way to write to the table.

Schema follows spec §10.1 exactly. ``ensure_restructuring_log_table`` matches
the cohort-bands convention (``ensure_cohort_bands_table``): IDEMPOTENT
``CREATE TABLE IF NOT EXISTS`` then a best-effort commit.

The writer validates inputs against the closed enums in
``protocol.reason_codes`` so the audit table can never accumulate strings
outside the vocabulary the rest of the protocol dispatches on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
  AppliedBy,
  ReasonCode,
  StepType,
  reason_code_belongs_to_mode,
)


RESTRUCTURING_LOG_TABLE_NAME = "post_intake_restructuring_log"

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {RESTRUCTURING_LOG_TABLE_NAME} (
  id                    BIGINT NOT NULL AUTO_INCREMENT,
  draft_id              VARCHAR(64)  NOT NULL,
  planning_run_id       VARCHAR(64)  NOT NULL,
  failure_mode          VARCHAR(32)  NOT NULL,
  cascade_tier          VARCHAR(8)   NOT NULL,
  cascade_tier_name     VARCHAR(64)  NOT NULL,
  reason_code           VARCHAR(64)  NOT NULL,
  section               VARCHAR(32)  NOT NULL,
  field                 VARCHAR(128) NULL,
  quarter_index         INT          NULL,
  original_value        DECIMAL(18,6) NULL,
  proposed_value        DECIMAL(18,6) NULL,
  applied_value         DECIMAL(18,6) NULL,
  step_type             VARCHAR(8)   NOT NULL,
  applied_by            VARCHAR(48)  NOT NULL,
  veto_reason           VARCHAR(512) NULL,
  evaluate_plan_round   INT          NOT NULL,
  worst_check_before    VARCHAR(128) NULL,
  worst_distance_before DECIMAL(18,6) NULL,
  worst_check_after     VARCHAR(128) NULL,
  worst_distance_after  DECIMAL(18,6) NULL,
  created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_draft_run (draft_id, planning_run_id),
  KEY ix_mode_tier (failure_mode, cascade_tier),
  KEY ix_reason   (reason_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


_VETO_REASON_MAX_LEN = 512


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

def ensure_restructuring_log_table(conn) -> None:
  """Idempotently create the restructuring-log table.

  Mirrors ``ensure_cohort_bands_table``: silent on existing tables, swallows
  trailing commit exceptions (some adapters auto-commit DDL).
  """
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
# Row dataclass — the typed argument shape preferred by callers.
# ---------------------------------------------------------------------------

@dataclass
class RestructureLogEntry:
  """One row about to be written. Mirrors spec §10.1 column-by-column.

  Use ``RestructureLogEntry(...)`` to assemble a row, then call
  ``log_restructure(conn, entry)`` to commit it. Or pass kwargs directly to
  ``log_restructure`` — both shapes are supported (kwargs are coerced into
  this dataclass internally).
  """
  draft_id: str
  planning_run_id: str
  failure_mode: FailureMode
  cascade_tier: str            # 'V1'..'V8', 'G1'..'G7', etc.
  cascade_tier_name: str
  reason_code: ReasonCode
  section: str
  step_type: StepType
  applied_by: AppliedBy
  evaluate_plan_round: int
  field: Optional[str] = None
  quarter_index: Optional[int] = None
  original_value: Optional[float] = None
  proposed_value: Optional[float] = None
  applied_value: Optional[float] = None
  veto_reason: Optional[str] = None
  worst_check_before: Optional[str] = None
  worst_distance_before: Optional[float] = None
  worst_check_after: Optional[str] = None
  worst_distance_after: Optional[float] = None


def _coerce_enum(value: Any, enum_cls):
  if value is None:
    return None
  if isinstance(value, enum_cls):
    return value
  try:
    return enum_cls(value)
  except Exception:
    return enum_cls[value]  # try by name; raises KeyError on miss


def _str_or_none(value: Any, *, max_len: Optional[int] = None) -> Optional[str]:
  if value is None:
    return None
  s = str(value).strip()
  if not s:
    return None
  if max_len is not None and len(s) > max_len:
    return s[:max_len]
  return s


def _decimal_or_none(value: Any) -> Optional[Decimal]:
  if value is None:
    return None
  if isinstance(value, Decimal):
    return value
  try:
    return Decimal(str(float(value)))
  except Exception:
    return None


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def log_restructure(
  conn,
  entry: Optional[Union[RestructureLogEntry, Dict[str, Any]]] = None,
  *,
  ensure_table: bool = True,
  **kwargs: Any,
) -> Optional[int]:
  """Insert one ``post_intake_restructuring_log`` row.

  Returns the new row's ``id`` on success, ``None`` if no connection.
  Raises ``ValueError`` for enum / required-field violations (these are bugs
  in the caller — every audit row should be valid).

  Accepts either a ``RestructureLogEntry`` (preferred) or a kwargs splat.
  Kwargs match dataclass fields one-to-one.
  """
  if entry is None and kwargs:
    entry = RestructureLogEntry(**kwargs)  # type: ignore[arg-type]
  elif entry is not None and kwargs:
    raise ValueError("pass either an entry dataclass OR kwargs, not both")
  elif entry is None:
    raise ValueError("log_restructure requires an entry or kwargs")

  if isinstance(entry, dict):
    entry = RestructureLogEntry(**entry)  # type: ignore[arg-type]

  # Coerce enums (caller may pass string values; we validate against the
  # closed enum sets here so SQL never sees an unknown string).
  failure_mode = _coerce_enum(entry.failure_mode, FailureMode)
  reason_code  = _coerce_enum(entry.reason_code,  ReasonCode)
  step_type    = _coerce_enum(entry.step_type,    StepType)
  applied_by   = _coerce_enum(entry.applied_by,   AppliedBy)

  if failure_mode is None or reason_code is None or step_type is None or applied_by is None:
    raise ValueError(
      f"missing enum value: failure_mode={entry.failure_mode!r}, "
      f"reason_code={entry.reason_code!r}, step_type={entry.step_type!r}, "
      f"applied_by={entry.applied_by!r}"
    )

  # (mode, reason_code) pairing rule — catches lookup typos at write time.
  if not reason_code_belongs_to_mode(reason_code, failure_mode):
    raise ValueError(
      f"reason_code {reason_code.value!r} is not valid for "
      f"failure_mode {failure_mode.value!r} "
      f"(see protocol.reason_codes.REASON_CODES_BY_MODE)"
    )

  draft_id = _str_or_none(entry.draft_id)
  planning_run_id = _str_or_none(entry.planning_run_id)
  if not draft_id or not planning_run_id:
    raise ValueError("draft_id and planning_run_id are required")

  cascade_tier = _str_or_none(entry.cascade_tier, max_len=8)
  cascade_tier_name = _str_or_none(entry.cascade_tier_name, max_len=64)
  section = _str_or_none(entry.section, max_len=32)
  if not cascade_tier or not cascade_tier_name or not section:
    raise ValueError(
      "cascade_tier, cascade_tier_name, and section are required"
    )

  evaluate_plan_round = int(entry.evaluate_plan_round)

  field_name = _str_or_none(entry.field, max_len=128)
  quarter_index = (
    int(entry.quarter_index) if entry.quarter_index is not None else None
  )

  original_value = _decimal_or_none(entry.original_value)
  proposed_value = _decimal_or_none(entry.proposed_value)
  applied_value  = _decimal_or_none(entry.applied_value)

  veto_reason = _str_or_none(entry.veto_reason, max_len=_VETO_REASON_MAX_LEN)

  worst_check_before = _str_or_none(entry.worst_check_before, max_len=128)
  worst_distance_before = _decimal_or_none(entry.worst_distance_before)
  worst_check_after = _str_or_none(entry.worst_check_after, max_len=128)
  worst_distance_after = _decimal_or_none(entry.worst_distance_after)

  # Veto rows MUST have an applied_value of None (no state change occurred).
  # This is a structural invariant of the spec §10.4 contract.
  if applied_by == AppliedBy.AMALGAMATED_GPT_VETOED and applied_value is not None:
    raise ValueError(
      "veto rows must not carry an applied_value (no state changed); "
      "set applied_value=None"
    )

  if conn is None:
    return None

  if ensure_table:
    ensure_restructuring_log_table(conn)

  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      INSERT INTO {RESTRUCTURING_LOG_TABLE_NAME}
        (draft_id, planning_run_id, failure_mode, cascade_tier,
         cascade_tier_name, reason_code, section, field, quarter_index,
         original_value, proposed_value, applied_value, step_type,
         applied_by, veto_reason, evaluate_plan_round,
         worst_check_before, worst_distance_before,
         worst_check_after,  worst_distance_after)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      """,
      (
        draft_id, planning_run_id, failure_mode.value, cascade_tier,
        cascade_tier_name, reason_code.value, section, field_name,
        quarter_index, original_value, proposed_value, applied_value,
        step_type.value, applied_by.value, veto_reason, evaluate_plan_round,
        worst_check_before, worst_distance_before,
        worst_check_after,  worst_distance_after,
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
# Read helper — for tests and Phase-4 verification.
# ---------------------------------------------------------------------------

def fetch_restructuring_log(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  failure_mode: Optional[Union[FailureMode, str]] = None,
  reason_code: Optional[Union[ReasonCode, str]] = None,
) -> List[Dict[str, Any]]:
  """Return rows for the (draft_id, planning_run_id) pair, oldest first.

  Optional filters narrow the result set. Used by tests and Phase-4
  verification scenarios to assert "this cascade attempted these tiers in
  this order with these outcomes."
  """
  if conn is None:
    return []

  where: List[str] = ["draft_id=%s", "planning_run_id=%s"]
  params: List[Any] = [draft_id, planning_run_id]

  if failure_mode is not None:
    fm = _coerce_enum(failure_mode, FailureMode)
    where.append("failure_mode=%s")
    params.append(fm.value if fm is not None else str(failure_mode))

  if reason_code is not None:
    rc = _coerce_enum(reason_code, ReasonCode)
    where.append("reason_code=%s")
    params.append(rc.value if rc is not None else str(reason_code))

  sql = (
    f"SELECT * FROM {RESTRUCTURING_LOG_TABLE_NAME} "
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
  "RESTRUCTURING_LOG_TABLE_NAME",
  "RestructureLogEntry",
  "ensure_restructuring_log_table",
  "log_restructure",
  "fetch_restructuring_log",
]
