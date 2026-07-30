"""Persona-run vitals: durable per-turn / per-GPT-call / per-event capture.

Why this exists
---------------
Persona sessions (a browser-driven client, e.g. Claude Cowork) produce runs
whose diagnosis today lives in scattered places: the timestamped server log
(REQ / TURN_BEGIN lines), post_intake_handler_traces (post-intake GPT I/O),
and the planning_* tables. None of them answer cheap aggregate questions like
"which sections have the slowest turns" or "which runs hit holds" without log
archaeology. This module is the queryable vitals layer: one row per intake
turn, one row per GPT HTTP call (both intake and post-intake phases), one row
per notable event, and one summary row per run (written by the session
watcher's finalizer when a watch ends).

Design contract (same as post_intake_handler_traces)
----------------------------------------------------
1. Instrumentation must NEVER break the pipeline: every public entry point is
   fully wrapped; a DB outage degrades to no-op and is swallowed.
2. INSERT-only, never UPDATE/DELETE.
3. Per-row connection + commit so rows are durable the instant they happen —
   a crash mid-turn leaves every prior row queryable.
4. Turn context is process-global (serial persona runs by design — one
   concurrent consult turn per server process; overlapping consult POSTs
   would attribute GPT calls to the newest turn, which matches the serial
   doctrine documented in docs/persona_run_observability.md).

Capture points
--------------
- api_handlers.intake_consult TURN_BEGIN  -> begin_turn(...)
- api.py after_request on /api/intake-consult POST -> finish_turn(...)
  (turn latency, HTTP status, reply size, section after the turn)
- client_intake_and_finmo.openai_http.post_openai_with_retries
  -> record_gpt_call(...) for EVERY GPT HTTP call in the process: elapsed,
  attempts (attempts > 1 == retried), status, token usage, response-lock
  replay flag, model, schema/call label. Phase attribution: an armed intake
  turn wins; else an active post_intake_handler_traces run; else
  'unattributed'. decision_source for post-intake calls stays in
  post_intake_handler_traces (join on draft_id + time window) — it is not
  duplicated here.
- TURN_HOLD / consult errors -> record_event(...)
- scripts/persona_run_vitals_finalize.py -> insert_run_summary(...) +
  watcher-sourced events (stall, terminal, transcript link).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

TURNS_TABLE = "run_vitals_turns"
GPT_CALLS_TABLE = "run_vitals_gpt_calls"
EVENTS_TABLE = "run_vitals_events"
RUNS_TABLE = "run_vitals_runs"

_CREATE_TURNS_SQL = f"""
CREATE TABLE IF NOT EXISTS {TURNS_TABLE} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  client_id VARCHAR(32) NOT NULL DEFAULT '',
  turn_index INT NOT NULL,
  section VARCHAR(32) NOT NULL DEFAULT '',
  section_after VARCHAR(32) NOT NULL DEFAULT '',
  is_starting TINYINT(1) NOT NULL DEFAULT 0,
  message_chars INT NULL,
  reply_chars INT NULL,
  http_status INT NULL,
  latency_ms INT NULL,
  gpt_calls INT NOT NULL DEFAULT 0,
  gpt_elapsed_ms BIGINT NOT NULL DEFAULT 0,
  gpt_tokens_in BIGINT NOT NULL DEFAULT 0,
  gpt_tokens_out BIGINT NOT NULL DEFAULT 0,
  gpt_lock_replays INT NOT NULL DEFAULT 0,
  gpt_retries INT NOT NULL DEFAULT 0,
  hold TINYINT(1) NOT NULL DEFAULT 0,
  error VARCHAR(255) NULL,
  call_labels_json LONGTEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_turns_draft (draft_id, turn_index),
  KEY ix_turns_section (section),
  KEY ix_turns_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_GPT_CALLS_SQL = f"""
CREATE TABLE IF NOT EXISTS {GPT_CALLS_TABLE} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL DEFAULT '',
  planning_run_id VARCHAR(64) NOT NULL DEFAULT '',
  phase VARCHAR(16) NOT NULL,
  turn_index INT NULL,
  section VARCHAR(32) NOT NULL DEFAULT '',
  call_label VARCHAR(128) NOT NULL DEFAULT '',
  model VARCHAR(64) NOT NULL DEFAULT '',
  status_code INT NULL,
  attempts INT NOT NULL DEFAULT 1,
  elapsed_ms INT NULL,
  tokens_in INT NULL,
  tokens_out INT NULL,
  tokens_total INT NULL,
  lock_replay TINYINT(1) NOT NULL DEFAULT 0,
  error VARCHAR(255) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_gpt_draft_created (draft_id, created_at),
  KEY ix_gpt_phase (phase),
  KEY ix_gpt_label (call_label),
  KEY ix_gpt_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_EVENTS_SQL = f"""
CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL DEFAULT '',
  planning_run_id VARCHAR(64) NOT NULL DEFAULT '',
  source VARCHAR(16) NOT NULL DEFAULT 'app',
  event_type VARCHAR(48) NOT NULL,
  detail_json LONGTEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_events_draft_created (draft_id, created_at),
  KEY ix_events_type (event_type),
  KEY ix_events_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_RUNS_SQL = f"""
CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  client_id VARCHAR(32) NOT NULL DEFAULT '',
  business_name VARCHAR(255) NULL,
  planning_run_id VARCHAR(64) NOT NULL DEFAULT '',
  exit_reason VARCHAR(32) NOT NULL DEFAULT '',
  draft_status VARCHAR(32) NOT NULL DEFAULT '',
  run_status VARCHAR(32) NOT NULL DEFAULT '',
  planning_stage VARCHAR(64) NOT NULL DEFAULT '',
  coherence_status VARCHAR(32) NOT NULL DEFAULT '',
  turns INT NOT NULL DEFAULT 0,
  intake_first_turn_at DATETIME(6) NULL,
  intake_last_turn_at DATETIME(6) NULL,
  total_turn_ms BIGINT NOT NULL DEFAULT 0,
  gpt_calls INT NOT NULL DEFAULT 0,
  gpt_elapsed_ms BIGINT NOT NULL DEFAULT 0,
  gpt_tokens_in BIGINT NOT NULL DEFAULT 0,
  gpt_tokens_out BIGINT NOT NULL DEFAULT 0,
  gpt_lock_replays INT NOT NULL DEFAULT 0,
  holds INT NOT NULL DEFAULT 0,
  errors INT NOT NULL DEFAULT 0,
  stalls INT NOT NULL DEFAULT 0,
  run_started_at DATETIME(6) NULL,
  run_completed_at DATETIME(6) NULL,
  run_seconds INT NULL,
  transcript_path VARCHAR(512) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_runs_draft (draft_id),
  KEY ix_runs_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_ALL_CREATE_SQL = (
  _CREATE_TURNS_SQL,
  _CREATE_GPT_CALLS_SQL,
  _CREATE_EVENTS_SQL,
  _CREATE_RUNS_SQL,
)

_MAX_LABEL_CHARS = 128
_MAX_ERROR_CHARS = 255


# ----------------------------------------------------------------------------
# Turn context (process-global; serial persona runs by design).
# ----------------------------------------------------------------------------

_lock = threading.Lock()
_turn: Optional[Dict[str, Any]] = None

# Once a DB write fails, stop retrying per-row so DB-less environments
# (unit tests, dry runs) don't pay a connection timeout on every row.
_persistence_disabled: bool = False
_tables_ready: bool = False


def _ensure_tables(conn) -> None:
  global _tables_ready
  if _tables_ready:
    return
  cur = conn.cursor()
  try:
    for stmt in _ALL_CREATE_SQL:
      cur.execute(stmt)
    try:
      conn.commit()
    except Exception:
      pass
    _tables_ready = True
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _insert_row(table: str, fields: Dict[str, Any]) -> None:
  """One row, own connection + commit, best-effort, never raises."""
  global _persistence_disabled
  if _persistence_disabled:
    return
  conn = None
  try:
    from client_intake_and_finmo.intake_submission import (  # type: ignore
      get_mysql_connection,
    )
    conn = get_mysql_connection()
    _ensure_tables(conn)
    cols = list(fields.keys())
    cur = conn.cursor()
    try:
      cur.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(fields[c] for c in cols),
      )
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      try:
        cur.close()
      except Exception:
        pass
  except Exception as exc:
    _persistence_disabled = True
    logger.debug("run_vitals_persist_disabled: %s", type(exc).__name__)
  finally:
    if conn is not None:
      try:
        conn.close()
      except Exception:
        pass


def _clip(text: Any, limit: int) -> str:
  s = str(text or "")
  return s[:limit]


# ----------------------------------------------------------------------------
# Turn lifecycle (intake consult).
# ----------------------------------------------------------------------------

def begin_turn(
  *,
  draft_id: Any,
  client_id: Any = "",
  turn_index: Any = None,
  section: Any = "",
  starting: bool = False,
  message_chars: Any = None,
) -> None:
  """Arm the per-turn accumulator at TURN_BEGIN. Re-arms persistence so a
  prior DB outage doesn't permanently silence a later run in the process."""
  global _turn, _persistence_disabled
  try:
    with _lock:
      _persistence_disabled = False
      _turn = {
        "draft_id": str(draft_id or "").strip(),
        "client_id": str(client_id or "").strip(),
        "turn_index": int(turn_index) if turn_index is not None else None,
        "section": _clip(section, 32),
        "starting": 1 if starting else 0,
        "message_chars": int(message_chars) if message_chars is not None else None,
        "started_monotonic": time.monotonic(),
        "gpt_calls": 0,
        "gpt_elapsed_ms": 0,
        "gpt_tokens_in": 0,
        "gpt_tokens_out": 0,
        "gpt_lock_replays": 0,
        "gpt_retries": 0,
        "hold": 0,
        "error": None,
        "call_labels": [],
      }
  except Exception as exc:  # pragma: no cover - defensive
    logger.debug("run_vitals_begin_turn_swallowed: %s", type(exc).__name__)


def mark_turn_hold(detail: Any = "") -> None:
  """Flag the armed turn as a hold (TURN_HOLD) and record the event row."""
  try:
    draft_id = ""
    with _lock:
      if _turn is not None:
        _turn["hold"] = 1
        draft_id = _turn["draft_id"]
    record_event(
      draft_id=draft_id,
      event_type="turn_hold",
      detail={"message": _clip(detail, 500)},
    )
  except Exception as exc:  # pragma: no cover - defensive
    logger.debug("run_vitals_mark_hold_swallowed: %s", type(exc).__name__)


def finish_turn(
  *,
  http_status: Any = None,
  latency_ms: Any = None,
  reply_chars: Any = None,
  section_after: Any = "",
  error: Any = None,
) -> None:
  """Flush the armed turn to run_vitals_turns and disarm. No-op when no
  turn is armed (e.g. requests rejected before TURN_BEGIN)."""
  global _turn
  try:
    with _lock:
      turn = _turn
      _turn = None
    if turn is None:
      return
    if latency_ms is None:
      latency_ms = int((time.monotonic() - turn["started_monotonic"]) * 1000.0)
    fields = {
      "draft_id": turn["draft_id"],
      "client_id": turn["client_id"],
      "turn_index": turn["turn_index"] if turn["turn_index"] is not None else -1,
      "section": turn["section"],
      "section_after": _clip(section_after, 32),
      "is_starting": turn["starting"],
      "message_chars": turn["message_chars"],
      "reply_chars": int(reply_chars) if reply_chars is not None else None,
      "http_status": int(http_status) if http_status is not None else None,
      "latency_ms": int(latency_ms) if latency_ms is not None else None,
      "gpt_calls": turn["gpt_calls"],
      "gpt_elapsed_ms": turn["gpt_elapsed_ms"],
      "gpt_tokens_in": turn["gpt_tokens_in"],
      "gpt_tokens_out": turn["gpt_tokens_out"],
      "gpt_lock_replays": turn["gpt_lock_replays"],
      "gpt_retries": turn["gpt_retries"],
      "hold": turn["hold"],
      "error": _clip(error, _MAX_ERROR_CHARS) or (turn["error"] or None),
      "call_labels_json": json.dumps(turn["call_labels"], ensure_ascii=False),
    }
    if fields["draft_id"]:
      _insert_row(TURNS_TABLE, fields)
  except Exception as exc:  # pragma: no cover - defensive
    logger.debug("run_vitals_finish_turn_swallowed: %s", type(exc).__name__)


# ----------------------------------------------------------------------------
# GPT call capture (hooked from openai_http.post_openai_with_retries).
# ----------------------------------------------------------------------------

def _post_intake_context() -> Dict[str, str]:
  try:
    from client_intake_and_finmo import post_intake_handler_traces as traces  # type: ignore
    active = traces.active_run()
    return {
      "draft_id": str(active.get("draft_id") or ""),
      "planning_run_id": str(active.get("planning_run_id") or ""),
    }
  except Exception:
    return {"draft_id": "", "planning_run_id": ""}


def record_gpt_call(
  *,
  url: Any = "",
  model: Any = "",
  call_label: Any = "",
  status_code: Any = None,
  attempts: Any = 1,
  elapsed_ms: Any = None,
  tokens_in: Any = None,
  tokens_out: Any = None,
  tokens_total: Any = None,
  lock_replay: bool = False,
  error: Any = None,
) -> None:
  """Record one GPT HTTP call. Phase attribution: an armed intake turn wins;
  else the active post-intake trace run; else 'unattributed'."""
  try:
    attempts_int = max(1, int(attempts or 1))
    fields: Dict[str, Any] = {
      "phase": "unattributed",
      "draft_id": "",
      "planning_run_id": "",
      "turn_index": None,
      "section": "",
      "call_label": _clip(call_label, _MAX_LABEL_CHARS),
      "model": _clip(model, 64),
      "status_code": int(status_code) if status_code is not None else None,
      "attempts": attempts_int,
      "elapsed_ms": int(elapsed_ms) if elapsed_ms is not None else None,
      "tokens_in": int(tokens_in) if tokens_in is not None else None,
      "tokens_out": int(tokens_out) if tokens_out is not None else None,
      "tokens_total": int(tokens_total) if tokens_total is not None else None,
      "lock_replay": 1 if lock_replay else 0,
      "error": _clip(error, _MAX_ERROR_CHARS) or None,
    }
    with _lock:
      turn = _turn
      if turn is not None:
        fields["phase"] = "intake"
        fields["draft_id"] = turn["draft_id"]
        fields["turn_index"] = turn["turn_index"]
        fields["section"] = turn["section"]
        turn["gpt_calls"] += 1
        turn["gpt_elapsed_ms"] += int(elapsed_ms or 0)
        turn["gpt_tokens_in"] += int(tokens_in or 0)
        turn["gpt_tokens_out"] += int(tokens_out or 0)
        turn["gpt_lock_replays"] += 1 if lock_replay else 0
        turn["gpt_retries"] += attempts_int - 1
        if error and not turn["error"]:
          turn["error"] = _clip(error, _MAX_ERROR_CHARS)
        turn["call_labels"].append(
          {
            "label": fields["call_label"],
            "model": fields["model"],
            "elapsed_ms": fields["elapsed_ms"],
            "tokens_in": fields["tokens_in"],
            "tokens_out": fields["tokens_out"],
            "lock_replay": bool(lock_replay),
            "attempts": attempts_int,
            "status": fields["status_code"],
            "error": fields["error"],
          }
        )
    if fields["phase"] == "unattributed":
      ctx = _post_intake_context()
      if ctx["draft_id"]:
        fields["phase"] = "post_intake"
        fields["draft_id"] = ctx["draft_id"]
        fields["planning_run_id"] = ctx["planning_run_id"]
    _insert_row(GPT_CALLS_TABLE, fields)
  except Exception as exc:  # pragma: no cover - defensive
    logger.debug("run_vitals_gpt_call_swallowed: %s", type(exc).__name__)


def extract_usage(body: Any) -> Dict[str, Optional[int]]:
  """Token usage from an OpenAI response body — Responses API
  (input_tokens/output_tokens) or chat completions (prompt/completion)."""
  out: Dict[str, Optional[int]] = {"tokens_in": None, "tokens_out": None, "tokens_total": None}
  try:
    usage = (body or {}).get("usage") or {}
    t_in = usage.get("input_tokens", usage.get("prompt_tokens"))
    t_out = usage.get("output_tokens", usage.get("completion_tokens"))
    t_tot = usage.get("total_tokens")
    out["tokens_in"] = int(t_in) if t_in is not None else None
    out["tokens_out"] = int(t_out) if t_out is not None else None
    out["tokens_total"] = int(t_tot) if t_tot is not None else None
  except Exception:
    pass
  return out


def extract_call_label(payload: Any) -> str:
  """Stable label identifying WHICH call this is: the structured-output
  schema name when present (e.g. 'intake_operating_model_final'), else ''."""
  try:
    p = payload or {}
    label = (((p.get("text") or {}).get("format") or {}).get("name")) or ""
    if not label:
      label = (((p.get("response_format") or {}).get("json_schema") or {}).get("name")) or ""
    if not label:
      # Unstructured call: the opening words of the instructions/system text
      # are stable per call site and identify it well enough.
      instructions = p.get("instructions")
      if not instructions:
        msgs = p.get("messages") or p.get("input") or []
        if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
          instructions = msgs[0].get("content")
      if isinstance(instructions, str) and instructions.strip():
        label = "~" + " ".join(instructions.split())[:80]
    return _clip(label, _MAX_LABEL_CHARS)
  except Exception:
    return ""


# ----------------------------------------------------------------------------
# Events + run summary (app- and watcher-sourced).
# ----------------------------------------------------------------------------

def record_event(
  *,
  draft_id: Any = "",
  event_type: Any,
  detail: Any = None,
  planning_run_id: Any = "",
  source: str = "app",
) -> None:
  try:
    _insert_row(
      EVENTS_TABLE,
      {
        "draft_id": str(draft_id or "").strip(),
        "planning_run_id": str(planning_run_id or "").strip(),
        "source": _clip(source, 16) or "app",
        "event_type": _clip(event_type, 48),
        "detail_json": json.dumps(detail, ensure_ascii=False, default=str)
        if detail is not None
        else None,
      },
    )
  except Exception as exc:  # pragma: no cover - defensive
    logger.debug("run_vitals_event_swallowed: %s", type(exc).__name__)


def insert_run_summary(fields: Dict[str, Any]) -> None:
  """One summary row per watched run (watcher finalizer). INSERT-only: a
  re-finalized run gets a second row; latest created_at wins."""
  try:
    allowed = {
      "draft_id", "client_id", "business_name", "planning_run_id",
      "exit_reason", "draft_status", "run_status", "planning_stage",
      "coherence_status", "turns", "intake_first_turn_at",
      "intake_last_turn_at", "total_turn_ms", "gpt_calls", "gpt_elapsed_ms",
      "gpt_tokens_in", "gpt_tokens_out", "gpt_lock_replays", "holds",
      "errors", "stalls", "run_started_at", "run_completed_at",
      "run_seconds", "transcript_path",
    }
    clean = {k: v for k, v in (fields or {}).items() if k in allowed}
    if clean.get("draft_id"):
      _insert_row(RUNS_TABLE, clean)
  except Exception as exc:  # pragma: no cover - defensive
    logger.debug("run_vitals_run_summary_swallowed: %s", type(exc).__name__)
