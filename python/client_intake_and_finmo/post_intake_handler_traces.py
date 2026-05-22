"""Phase 9 P3.32 K11 L-4 — Handler diagnostic trace infrastructure.

Why this exists
---------------
The pre-existing run-diagnostics path (``post_intake_run_diagnostics``)
is a SINGLE-SHOT BUFFERED model: the full planning_run_json (7-11 MB on
a completed run) is assembled in memory and flushed exactly once, at
orchestrator completion. Any exception before completion loses every
in-progress trace — this is the root cause of the 1.46 MB *truncated*
failure reports the Skyward investigation hit (P1.3). Hoping a failure
recurs to "confirm" cause is unacceptable when the instrumentation that
would show cause was never persisted.

This module fixes that at the source. It is an INCREMENTAL trace sink:
every Handler C GPT call, every H2 probe, and every OpenAI turn writes
its own row the moment it completes, in its own short-lived MySQL
connection + commit. A crash at probe N leaves probes 1..N durably on
disk, queryable per-draft / per-handler / per-call.

Design contract (NON-NEGOTIABLE)
--------------------------------
1. Instrumentation must NEVER break the pipeline. Every public entry
   point is fully wrapped: a DB outage, missing env, or serialization
   error degrades to in-memory-only (or no-op) and is swallowed.
2. INSERT-only, never UPDATE/DELETE — aligns with project SQL discipline
   (mirrors ``post_intake_run_diagnostics``).
3. Run-scoped, mirroring the ``_gpt_call_log`` pattern in
   ``_gpt_critic_io``: ``begin_trace_run`` clears the buffer and stamps
   the active (draft_id, planning_run_id); handlers append; the buffer
   is inspectable mid-run for P1.5 runtime observability.
4. No handler signature changes. The active run context is process-
   global (lock-protected), so deep call sites record without threading
   parameters through — the same mechanism ``_gpt_call_log`` already
   uses.

Capture verbosity
-----------------
By default each trace row carries the structured forensic payload the
investigation needs (per-call anchors, all 12 viability_checks,
stage_ramp_violations, validator results, OpenAI latency + token usage).
Verbatim full GPT request/response bodies are LARGE and mostly
reconstructable from code; set ``BPLAN_TRACE_VERBOSE=1`` to additionally
persist them. Either way, no field exceeds ``_MAX_FIELD_CHARS`` so a
pathological payload cannot produce an unbounded row.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# Handler identifiers (stable, queryable).
HANDLER_C = "handler_c_payroll"
HANDLER_H2 = "h2_exhaustion"
HANDLER_GPT_IO = "gpt_io"

# Trace kinds.
KIND_PER_CALL = "per_call"
KIND_GPT_IO = "gpt_io"
KIND_RUNTIME_STATUS = "runtime_status"

_MAX_FIELD_CHARS = 2_000_000  # generous per-field cap; LONGTEXT holds 4 GB.

_TABLE_NAME = "post_intake_handler_traces"
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NOT NULL,
  handler VARCHAR(32) NOT NULL,
  trace_kind VARCHAR(32) NOT NULL,
  call_n INT NULL,
  seq INT NOT NULL,
  elapsed_ms INT NULL,
  trace_json LONGTEXT NOT NULL,
  captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_draft_run (draft_id, planning_run_id),
  KEY ix_draft_handler (draft_id, handler),
  KEY ix_handler_kind (handler, trace_kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


# ----------------------------------------------------------------------------
# Run-scoped context (mirrors _gpt_call_log: process-global + lock).
# ----------------------------------------------------------------------------

_lock = threading.Lock()
_active_draft_id: str = ""
_active_planning_run_id: str = ""
_run_started_monotonic: float = 0.0
_seq: int = 0
_buffer: List[Dict[str, Any]] = []
_runtime_status: Dict[str, Dict[str, Any]] = {}

# Once a DB write fails (no env / not installed / unreachable), stop
# retrying per-call so DB-less environments (unit tests, dry runs) don't
# pay a connection timeout on every trace.
_persistence_disabled: bool = False


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def begin_trace_run(draft_id: Any, planning_run_id: Any = "") -> None:
  """Open a trace run. Clears the in-memory buffer and stamps the active
  draft_id (and planning_run_id if already known) for all subsequent
  ``record_*`` calls.

  MUST be called at the TRUE entry of the planning system run
  (_run_planning_system_for_draft_unified), BEFORE the initial grid /
  payroll Handler C runs — NOT at the orchestrator, which executes only
  after the grid is built. draft_id is sufficient to key a run (the
  runner clones each source into a fresh draft per execution);
  planning_run_id is created later inside the initial-grid build and is
  stamped via ``set_planning_run_id`` once known.

  Safe to call repeatedly; re-arms persistence (so a prior DB outage
  doesn't permanently silence a later run in the same process).
  """
  global _active_draft_id, _active_planning_run_id, _run_started_monotonic
  global _seq, _persistence_disabled
  with _lock:
    _active_draft_id = str(draft_id or "").strip()
    _active_planning_run_id = str(planning_run_id or "").strip()
    _run_started_monotonic = time.monotonic()
    _seq = 0
    _buffer.clear()
    _runtime_status.clear()
    _persistence_disabled = False


def set_planning_run_id(planning_run_id: Any) -> None:
  """Stamp the planning_run_id onto the active trace run once the
  initial-grid build has created it. Does NOT clear the buffer or reset
  the sequence — traces already recorded under the early (empty)
  planning_run_id stay durable and queryable by draft_id; subsequent
  traces carry the real id."""
  global _active_planning_run_id
  pid = str(planning_run_id or "").strip()
  if not pid:
    return
  with _lock:
    _active_planning_run_id = pid


def end_trace_run() -> None:
  """Close the trace run. The buffer is retained (the orchestrator may
  fold it into the final report); a fresh ``begin_trace_run`` clears it.
  """
  # Intentionally a no-op on the buffer — incremental rows are already
  # durable, and the in-memory buffer stays inspectable until the next
  # begin_trace_run. Present as the symmetric bookend for callers.
  return None


def _elapsed_run_ms() -> Optional[int]:
  if _run_started_monotonic <= 0.0:
    return None
  return int((time.monotonic() - _run_started_monotonic) * 1000.0)


def _verbose() -> bool:
  return str(os.getenv("BPLAN_TRACE_VERBOSE") or "").strip().lower() in {
    "1", "true", "yes", "y"
  }


def _bounded_json(value: Any) -> str:
  """Serialize to JSON, never raising, never exceeding _MAX_FIELD_CHARS."""
  try:
    text = json.dumps(value, ensure_ascii=False, default=str)
  except Exception as exc:  # pragma: no cover - defensive
    text = json.dumps({"_trace_serialize_error": type(exc).__name__})
  if len(text) > _MAX_FIELD_CHARS:
    text = text[:_MAX_FIELD_CHARS] + '..."<truncated>"'
  return text


# ----------------------------------------------------------------------------
# Durable (incremental) persistence — best-effort, own connection per row.
# ----------------------------------------------------------------------------

def _ensure_table(conn) -> None:
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


def _persist_row(entry: Dict[str, Any], trace_json: str) -> None:
  """Insert one trace row in its own connection + commit. The per-row
  connection is what makes the trace crash-survivable: rows are durable
  the instant the call that produced them completes, independent of
  whether the run later raises. Best-effort — any failure disables
  further DB writes for this run and is swallowed.
  """
  global _persistence_disabled
  if _persistence_disabled:
    return
  conn = None
  try:
    from client_intake_and_finmo.intake_submission import (  # type: ignore
      get_mysql_connection,
    )
    conn = get_mysql_connection()
    _ensure_table(conn)
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        INSERT INTO {_TABLE_NAME} (
          draft_id, planning_run_id, handler, trace_kind,
          call_n, seq, elapsed_ms, trace_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
          entry["draft_id"], entry["planning_run_id"] or "pending",
          entry["handler"], entry["trace_kind"], entry.get("call_n"),
          entry["seq"], entry.get("elapsed_ms"), trace_json,
        ),
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
    # No DB available (unit tests, dry runs) or transient failure: fall
    # back to in-memory-only for the rest of the run.
    _persistence_disabled = True
    logger.debug("handler_trace_persist_disabled: %s", type(exc).__name__)
  finally:
    if conn is not None:
      try:
        conn.close()
      except Exception:
        pass


def _record(
  *,
  handler: str,
  trace_kind: str,
  payload: Dict[str, Any],
  call_n: Optional[int] = None,
  elapsed_ms: Optional[int] = None,
) -> None:
  """Append a trace entry to the in-memory buffer AND attempt an
  immediate durable insert. The single choke point for all record_*
  helpers. Fully best-effort: instrumentation never breaks the pipeline.
  """
  global _seq
  try:
    with _lock:
      _seq += 1
      entry = {
        "draft_id": _active_draft_id,
        "planning_run_id": _active_planning_run_id,
        "handler": str(handler),
        "trace_kind": str(trace_kind),
        "call_n": int(call_n) if call_n is not None else None,
        "seq": _seq,
        "elapsed_ms": elapsed_ms,
        "captured_at": _now_iso(),
        "run_elapsed_ms": _elapsed_run_ms(),
        "payload": payload,
      }
      _buffer.append(entry)
      snapshot = dict(entry)
    trace_json = _bounded_json(snapshot)
    # draft_id alone keys a run (fresh clone per execution). planning_run_id
    # may not exist yet when payroll Handler C runs during the initial-grid
    # build — persist anyway with a "pending" placeholder so that early
    # trace is durable; set_planning_run_id stamps later traces.
    if snapshot["draft_id"]:
      _persist_row(snapshot, trace_json)
  except Exception as exc:  # pragma: no cover - defensive
    logger.debug("handler_trace_record_swallowed: %s", type(exc).__name__)


# ----------------------------------------------------------------------------
# Public record helpers (called from the instrumented handlers).
# ----------------------------------------------------------------------------

def record_gpt_io(
  *,
  consultant_name: str,
  decision_source: str,
  model: str = "",
  elapsed_ms: Optional[int] = None,
  usage: Optional[Dict[str, Any]] = None,
  tool_call_names: Optional[List[str]] = None,
  error: Optional[Dict[str, Any]] = None,
  request_summary: Optional[Dict[str, Any]] = None,
  raw_request: Optional[Dict[str, Any]] = None,
  raw_response: Optional[Dict[str, Any]] = None,
) -> None:
  """Record one OpenAI turn's telemetry (P1.1/P1.2 API-level capture).

  This is the layer that captures latency + token usage + the
  Skyward-class read-timeout error context. Verbatim request/response
  bodies are persisted only under BPLAN_TRACE_VERBOSE=1.
  """
  payload: Dict[str, Any] = {
    "consultant_name": str(consultant_name or ""),
    "decision_source": str(decision_source or ""),
    "model": str(model or ""),
    "elapsed_ms": elapsed_ms,
    "usage": usage or {},
    "tool_call_names": list(tool_call_names or []),
  }
  if error:
    payload["error"] = error
  if request_summary:
    payload["request_summary"] = request_summary
  if _verbose():
    if raw_request is not None:
      payload["raw_request"] = raw_request
    if raw_response is not None:
      payload["raw_response"] = raw_response
  _record(
    handler=HANDLER_GPT_IO,
    trace_kind=KIND_GPT_IO,
    payload=payload,
    elapsed_ms=elapsed_ms,
  )


def record_handler_call(
  *,
  handler: str,
  call_n: int,
  payload: Dict[str, Any],
) -> None:
  """Record one handler probe/tool-call (P1.1 Handler C, P1.2 H2).

  ``payload`` is the structured forensic record for the call: proposed
  drivers/anchors or arguments, viability_checks, stage_ramp_violations,
  validator results, etc. The caller owns its shape; this module only
  guarantees durability and bounding.
  """
  _record(
    handler=str(handler),
    trace_kind=KIND_PER_CALL,
    payload=payload or {},
    call_n=call_n,
  )


def record_runtime_status(
  *,
  handler: str,
  status: Dict[str, Any],
) -> None:
  """Record / refresh a handler's mid-execution runtime status (P1.5).

  This is the foundation for preemptive problem detection: active
  constraints and their satisfaction, distance-to-feasibility, budget
  remaining, time elapsed. Latest snapshot per handler is queryable via
  ``get_runtime_status`` mid-run; every update is also persisted so the
  trajectory survives a crash.
  """
  snap = dict(status or {})
  snap["_captured_at"] = _now_iso()
  with _lock:
    _runtime_status[str(handler)] = snap
  _record(
    handler=str(handler),
    trace_kind=KIND_RUNTIME_STATUS,
    payload=snap,
  )


# ----------------------------------------------------------------------------
# Inspection (P1.5 runtime observability + post-mortem buffer access).
# ----------------------------------------------------------------------------

def get_runtime_status(handler: Optional[str] = None) -> Dict[str, Any]:
  """Latest runtime-status snapshot. Pass a handler id for one handler,
  or omit for all handlers. Inspectable mid-execution."""
  with _lock:
    if handler is not None:
      return dict(_runtime_status.get(str(handler), {}))
    return {k: dict(v) for k, v in _runtime_status.items()}


def get_trace_buffer(
  *,
  handler: Optional[str] = None,
  trace_kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
  """In-memory trace entries for the active run, optionally filtered.
  The orchestrator can fold this into the final report; tests inspect it
  directly when no DB is configured."""
  with _lock:
    rows = list(_buffer)
  if handler is not None:
    rows = [r for r in rows if r.get("handler") == handler]
  if trace_kind is not None:
    rows = [r for r in rows if r.get("trace_kind") == trace_kind]
  return [dict(r) for r in rows]


def active_run() -> Dict[str, Any]:
  with _lock:
    return {
      "draft_id": _active_draft_id,
      "planning_run_id": _active_planning_run_id,
      "trace_count": len(_buffer),
      "persistence_disabled": _persistence_disabled,
    }


def load_traces_for_draft(
  conn,
  *,
  draft_id: str,
  planning_run_id: Optional[str] = None,
  handler: Optional[str] = None,
) -> List[Dict[str, Any]]:
  """Read persisted traces back for comparative analysis (Phase 2).
  Ordered by (planning_run_id, seq). Best-effort: returns [] on any
  failure or if the table does not yet exist."""
  rows: List[Dict[str, Any]] = []
  try:
    _ensure_table(conn)
    where = ["draft_id = %s"]
    params: List[Any] = [str(draft_id or "")]
    if planning_run_id:
      where.append("planning_run_id = %s")
      params.append(str(planning_run_id))
    if handler:
      where.append("handler = %s")
      params.append(str(handler))
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        SELECT draft_id, planning_run_id, handler, trace_kind, call_n,
               seq, elapsed_ms, trace_json, captured_at
        FROM {_TABLE_NAME}
        WHERE {' AND '.join(where)}
        ORDER BY planning_run_id ASC, seq ASC
        """,
        tuple(params),
      )
      cols = [d[0] for d in cur.description]
      for raw in cur.fetchall():
        row = dict(zip(cols, raw))
        tj = row.get("trace_json")
        if isinstance(tj, (bytes, bytearray)):
          tj = tj.decode("utf-8", "replace")
        try:
          row["trace"] = json.loads(tj) if tj else {}
        except Exception:
          row["trace"] = {}
        row.pop("trace_json", None)
        rows.append(row)
    finally:
      try:
        cur.close()
      except Exception:
        pass
  except Exception as exc:
    logger.debug("load_traces_for_draft_failed: %s", type(exc).__name__)
  return rows
