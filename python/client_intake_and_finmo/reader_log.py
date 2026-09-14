"""WHO ELSE READ HER WORDS - one-reader build, step 1b (Nick ruled 2026-09-14).

Nick's rule: a client's sentence is interpreted ONCE, by the router. Last
night's search found about 45 places that pull meaning from her words
themselves, and Nick said to assume there are more. This turns the estimate
into a count.

Every function that reads a client's words carries @reads_client_words(name).
Inside a live request each call is noted - the reader, the call site, whether
the text it was handed IS her message this turn, and what it concluded - and the
turn's notes are written once at the end of the request. Beside the shadow
interpretation (step 1) that gives, per turn: what each reader took her sentence
to mean, and where it disagreed with the one reading.

It changes nothing a reader returns: the decorator calls the function and
returns its result or re-raises its exception, untouched. Outside a request
(unit tests, preflight, the shadow's own thread) nothing is noted. A reader that
never runs during the window is never counted - the count is of readers that
READ, and REGISTERED is the list of readers that COULD.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import sys
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE = "intake_turn_reader_extracts"
MAX_PER_TURN = 600
REGISTERED: set = set()

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  turn INT NULL,
  reader VARCHAR(64) NOT NULL,
  call_site VARCHAR(160) NOT NULL DEFAULT '',
  is_client_text TINYINT(1) NOT NULL DEFAULT 0,
  calls INT NOT NULL DEFAULT 1,
  result_json TEXT NULL,
  error VARCHAR(128) NULL,
  args_json TEXT NULL,
  created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_draft_turn (draft_id, turn),
  KEY ix_reader (reader)
)
"""
_ensured = False
_lock = threading.Lock()


def _connect():
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  return get_mysql_connection()


def _ensure(conn) -> None:
  global _ensured
  if _ensured:
    return
  with _lock:
    if _ensured:
      return
    cur = conn.cursor()
    try:
      cur.execute(_DDL)
      # args_json came after the first build (Cowork 1064); errno 1060 = present
      try:
        cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN args_json TEXT NULL")
      except Exception as exc:
        if getattr(exc, "errno", None) != 1060:
          raise
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
    _ensured = True


def _bucket(create: bool = True) -> Optional[Dict[str, Any]]:
  try:
    from flask import g, has_request_context  # type: ignore
  except Exception:
    return None
  if not has_request_context():
    return None
  b = getattr(g, "_reader_extracts", None)
  if b is None and create:
    b = {"rows": {}, "dropped": 0}
    g._reader_extracts = b
  return b


def _is_client_text(args, kwargs) -> bool:
  try:
    from flask import g  # type: ignore
    client = str(getattr(g, "_turn_user_text", "") or "").strip()
  except Exception:
    return False
  if not client:
    return False
  for v in list(args) + list(kwargs.values()):
    if isinstance(v, str):
      s = v.strip()
      if s and (s == client or client in s):
        return True
    elif isinstance(v, (list, tuple)):
      if any(isinstance(x, str) and x.strip() == client for x in v):
        return True
  return False


def _summarise_args(args, kwargs) -> str:
  """WHAT THE READER WAS GIVEN (Cowork 1064: a result without its input cannot say
  which number was judged unsaid). Her message is replaced by a marker - it is
  already in the transcript and a note must not become a second copy of it; other
  text is cut short; numbers, flags and small structures are kept."""
  try:
    from flask import g  # type: ignore
    client = str(getattr(g, "_turn_user_text", "") or "").strip()
  except Exception:
    client = ""

  def one(v: Any) -> Any:
    if isinstance(v, str):
      s = v.strip()
      if client and s == client:
        return "<her message>"
      if client and client in s:
        return "<text containing her message>"
      return v[:80]
    if v is None or isinstance(v, (bool, int, float)):
      return v
    try:
      return json.dumps(v, ensure_ascii=False, default=str)[:200]
    except Exception:
      return repr(v)[:200]

  try:
    return json.dumps({"args": [one(a) for a in args], "kwargs": {str(k): one(v) for k, v in kwargs.items()}},
                      ensure_ascii=False, default=str)[:600]
  except Exception:
    return ""


def _note(name: str, args, kwargs, result: Any, exc: Optional[BaseException]) -> None:
  try:
    b = _bucket()
    if b is None:
      return
    try:
      f = sys._getframe(2)
      site = "%s:%s %s" % (os.path.basename(f.f_code.co_filename), f.f_lineno, f.f_code.co_name)
    except Exception:
      site = ""
    try:
      rj = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
      rj = repr(result)
    key = (name, site[:160], _is_client_text(args, kwargs), rj[:1500], type(exc).__name__ if exc else None,
           _summarise_args(args, kwargs))
    rows = b["rows"]
    if key in rows:
      rows[key] += 1
    elif len(rows) >= MAX_PER_TURN:
      b["dropped"] += 1
    else:
      rows[key] = 1
  except Exception:  # noqa: BLE001 - noting a read must never touch the read
    pass


def reads_client_words(name: str):
  """Mark a function that pulls meaning from a client's words. Transparent."""
  def deco(fn):
    REGISTERED.add(name)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
      try:
        result = fn(*args, **kwargs)
      except Exception as exc:
        _note(name, args, kwargs, None, exc)
        raise
      _note(name, args, kwargs, result, None)
      return result

    wrapper.__reads_client_words__ = name
    return wrapper
  return deco


def flush() -> int:
  """Write this request's notes, once. Returns rows written. Never raises."""
  b = _bucket(create=False)
  if not b or not b.get("rows"):
    return 0
  try:
    from flask import g  # type: ignore
    from client_intake_and_finmo.openai_http import get_gpt_run_identity  # type: ignore
    draft_id = str((get_gpt_run_identity() or {}).get("draft_id") or "").strip()
    turn = getattr(g, "_turn_index", None)
    turn = int(turn) if isinstance(turn, int) else None
  except Exception:
    draft_id, turn = "", None
  rows, dropped = b["rows"], b.get("dropped", 0)
  b["rows"], b["dropped"] = {}, 0
  if not draft_id:
    return 0
  params = [(draft_id, turn, name, site, 1 if is_client else 0, calls, rj, err, aj)
            for (name, site, is_client, rj, err, aj), calls in rows.items()]
  try:
    conn = _connect()
    try:
      _ensure(conn)
      cur = conn.cursor()
      try:
        cur.executemany(
          f"INSERT INTO {TABLE} (draft_id, turn, reader, call_site, is_client_text, calls, result_json, error, args_json) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", params)
        try:
          conn.commit()
        except Exception:
          pass
      finally:
        cur.close()
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:  # noqa: BLE001
    logger.error("READER_EXTRACTS_WRITE_FAILED draft=%s turn=%s rows=%d: %s", draft_id, turn, len(params), exc)
    return 0
  if dropped:
    logger.warning("READER_EXTRACTS_CAPPED draft=%s turn=%s dropped=%d distinct notes beyond %d",
                   draft_id, turn, dropped, MAX_PER_TURN)
  return len(params)


def for_draft(conn, draft_id: str) -> List[Dict[str, Any]]:
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(f"SELECT turn, reader, call_site, is_client_text, calls, result_json, error, args_json, created_at "
                f"FROM {TABLE} WHERE draft_id=%s ORDER BY id", (str(draft_id),))
    out = []
    for r in cur.fetchall():
      row = dict(r)
      for src, dst in (("result_json", "result"), ("args_json", "args")):
        raw = row.pop(src, None)
        try:
          row[dst] = json.loads(raw) if raw else None
        except Exception:
          row[dst] = raw
      row["is_client_text"] = bool(row.get("is_client_text"))
      out.append(row)
    return out
  finally:
    cur.close()
