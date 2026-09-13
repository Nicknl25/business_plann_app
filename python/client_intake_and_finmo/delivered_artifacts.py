"""EVERY FILE WE HAND A CLIENT IS TRACEABLE TO THE RUN THAT MADE IT.

Until now nothing recorded where a delivery landed. `planning_runs` has no
path column, `run_vitals_runs` carries only a transcript path, and the two
delivery sites wrote their file and returned. So the only handle on a
delivered workbook was its filename - `Business Name -- MM-DD-YYYY HH-MM-SS
.xlsx` - which carries no draft id, no run id, and nothing inside the file
carries one either. Two workbooks for the same business in that folder and
there is no way to tell which run either came from, or which one a written
plan was written against.

One row per delivered file, written at the moment it lands:

    draft_id, planning_run_id, kind, path, name, bytes, sha256, delivered_at

The sha256 is what makes it a record rather than a note: a path can be
overwritten, and then the row and the file disagree and say so.

Best-effort like the intake guard's audit - a delivery must never fail
because its bookkeeping did - but never silent: a failed write logs at ERROR.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE = "delivered_artifacts"

#: The kinds that can be delivered. `render_report` is the writer's own
#: account of which figures and tables placed - it lives beside the plan and
#: answers "how many figures, did they place".
KINDS = ("workbook", "plan", "render_report")

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NULL,
  kind VARCHAR(16) NOT NULL,
  path VARCHAR(1024) NOT NULL,
  name VARCHAR(512) NOT NULL,
  bytes BIGINT NULL,
  sha256 CHAR(64) NULL,
  delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY ix_draft (draft_id, kind, delivered_at),
  KEY ix_run (planning_run_id)
)
"""

_ensured = False
_lock = threading.Lock()

#: Hashing a 300KB workbook is nothing; the cap is here so a pathological
#: file can never stall a delivery on its bookkeeping.
_MAX_HASH_BYTES = 256 * 1024 * 1024


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
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
    _ensured = True


def sha256_of(path: str) -> Optional[str]:
  try:
    if os.path.getsize(path) > _MAX_HASH_BYTES:
      return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
      for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()
  except OSError:
    return None


def record(conn, *, draft_id: str, planning_run_id: str = "", kind: str, path: str) -> Optional[int]:
  """One delivered file. Returns the row id, or None if it could not be
  written - and never raises, because a delivery that already happened must
  not be undone by its own bookkeeping."""
  try:
    if str(kind) not in KINDS:
      logger.error("DELIVERED_ARTIFACT_BAD_KIND kind=%r path=%r", kind, path)
      return None
    if not str(draft_id or "").strip():
      logger.error("DELIVERED_ARTIFACT_NO_DRAFT kind=%s path=%r - the file is delivered but unattributable", kind, path)
      return None
    try:
      size = os.path.getsize(path)
    except OSError:
      size = None
    digest = sha256_of(path)
    _ensure(conn)
    cur = conn.cursor()
    try:
      cur.execute(
        f"INSERT INTO {TABLE} (draft_id, planning_run_id, kind, path, name, bytes, sha256) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (str(draft_id), str(planning_run_id or "") or None, str(kind),
         str(path)[:1024], os.path.basename(str(path))[:512], size, digest),
      )
      row_id = cur.lastrowid
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
    logger.info("DELIVERED_ARTIFACT draft=%s run=%s kind=%s bytes=%s sha=%s path=%s",
                draft_id, planning_run_id or "-", kind, size, (digest or "-")[:12], path)
    return row_id
  except Exception as exc:  # noqa: BLE001 - bookkeeping never breaks a delivery
    logger.error("DELIVERED_ARTIFACT_WRITE_FAILED draft=%s kind=%s path=%r: %s", draft_id, kind, path, exc)
    return None


def for_draft(conn, draft_id: str, *, kind: str = "") -> List[Dict[str, Any]]:
  """Everything delivered for one draft, newest first - so a fresh build is
  distinguishable from a stale file sitting in the same folder."""
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    if kind:
      cur.execute(
        f"SELECT draft_id, planning_run_id, kind, path, name, bytes, sha256, delivered_at "
        f"FROM {TABLE} WHERE draft_id=%s AND kind=%s ORDER BY delivered_at DESC, id DESC",
        (str(draft_id), str(kind)))
    else:
      cur.execute(
        f"SELECT draft_id, planning_run_id, kind, path, name, bytes, sha256, delivered_at "
        f"FROM {TABLE} WHERE draft_id=%s ORDER BY delivered_at DESC, id DESC",
        (str(draft_id),))
    return [dict(r) for r in cur.fetchall()]
  finally:
    cur.close()


def latest(conn, draft_id: str, *, kind: str) -> Optional[Dict[str, Any]]:
  rows = for_draft(conn, draft_id, kind=kind)
  return rows[0] if rows else None


def verify(row: Dict[str, Any]) -> Dict[str, Any]:
  """Does the file still match the row? A path can be overwritten by a later
  run with the same name; the hash is what catches it."""
  path = str((row or {}).get("path") or "")
  out: Dict[str, Any] = {"path": path, "exists": os.path.isfile(path)}
  if not out["exists"]:
    out["state"] = "missing"
    return out
  out["bytes_now"] = os.path.getsize(path)
  recorded = (row or {}).get("sha256")
  if not recorded:
    out["state"] = "unverifiable"
    return out
  out["sha256_now"] = sha256_of(path)
  out["state"] = "intact" if out["sha256_now"] == recorded else "replaced"
  return out
