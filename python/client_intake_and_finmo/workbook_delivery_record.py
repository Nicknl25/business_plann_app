"""Which workbook belongs to which draft.

THE DEFECT THIS CLOSES (CW-031, found by mini auditing tier 1). The artifact
detector read the delivered workbook by globbing ``<business name>*.xlsx`` and
taking the newest by mtime. Five drafts share the business name "Thistledown
Cycle and Service", so the REAL client draft — whose ops rows carry no per-line
COGS at all — scored PASS on a workbook a different draft produced. A detector
that exists to stop false confirmations was minting one.

The fix is a binding, in two tiers, and NEITHER of them is "newest file wins":

  1. THE DELIVERY RECORD (authoritative, forward-looking). Every run that
     exports a workbook writes one INSERT-only row here naming the draft, the
     planning run, and the file. Reading it back is exact.
  2. THE RUN'S OWN WINDOW (legacy runs, before the record existed). The
     workbook filename embeds its export timestamp (``%m-%d-%Y %H-%M-%S``,
     local) and every planning run has its own timestamp in
     post_intake_run_diagnostics. A file is attributed to a draft only when
     that draft's OWN run stamp is the closest of ALL run stamps for that
     business name, and within a tight tolerance. A file that sits nearer some
     other draft's run belongs to that other draft, which is exactly the
     Thistledown case.

When neither tier can name a file, the answer is "not attributable" — never a
guess. The caller must then return not_applicable, because a workbook we cannot
bind is not evidence about this draft in either direction.

Why the diagnostics row could not simply carry it: run diagnostics are built
and persisted BEFORE the workbook is exported (the Diagnostics sheet renders
from the just-persisted row), and that table is INSERT-only by project
discipline, so ``workbook_path`` in it is None on every real run to date.
"""

from __future__ import annotations

import glob
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

TABLE_NAME = "workbook_deliveries"

# build_workbook_path(): f"{company} -- {written_at:%m-%d-%Y %H-%M-%S}.xlsx".
# The suffix group tolerates the restructure-attempt marker the delivery path
# can add to the primary workbook's name.
_FILENAME_STAMP_RE = re.compile(
  r"--\s*(\d{2}-\d{2}-\d{4} \d{2}-\d{2}-\d{2})(?:\s|\.|$)"
)
_FILENAME_STAMP_FORMAT = "%m-%d-%Y %H-%M-%S"

# How far a workbook's embedded stamp may sit from its run's recorded time.
# The two are written seconds apart (export immediately follows the diagnostics
# INSERT); 300s is slack for a slow build, not room to reach a neighbouring run.
DEFAULT_WINDOW_SECONDS = 300

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NOT NULL DEFAULT '',
  workbook_filename VARCHAR(255) NOT NULL,
  source_path TEXT NULL,
  delivered_path TEXT NULL,
  delivered_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_workbook_deliveries_draft (draft_id),
  KEY ix_workbook_deliveries_run (planning_run_id),
  UNIQUE KEY uniq_draft_run_file (draft_id, planning_run_id, workbook_filename)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def ensure_table(conn) -> None:
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


def record_workbook_delivery(
  conn,
  *,
  draft_id: str,
  planning_run_id: str = "",
  source_path: str = "",
  delivered_path: str = "",
) -> bool:
  """INSERT-only. Returns True when a new row landed.

  Called once per run, right after the primary workbook is exported and
  (optionally) copied to the delivery directory. ``delivered_path`` is empty
  when FINMO_MODEL_DELIVERY_DIR is unset or the copy failed — the binding to
  the SOURCE file still holds and is still worth recording.
  """
  draft_id = str(draft_id or "").strip()
  source_path = str(source_path or "").strip()
  delivered_path = str(delivered_path or "").strip()
  filename = os.path.basename(delivered_path or source_path)
  if not draft_id or not filename:
    return False
  ensure_table(conn)
  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      INSERT IGNORE INTO {TABLE_NAME}
        (draft_id, planning_run_id, workbook_filename, source_path, delivered_path)
      VALUES (%s, %s, %s, %s, %s)
      """,
      (draft_id, str(planning_run_id or "").strip(), filename,
       source_path or None, delivered_path or None),
    )
    rowcount = int(cur.rowcount or 0)
    try:
      conn.commit()
    except Exception:
      pass
    return rowcount > 0
  finally:
    try:
      cur.close()
    except Exception:
      pass


# ---------------------------------------------------------------------------
# Resolution.
# ---------------------------------------------------------------------------


def _stamp_from_filename(name: str) -> Optional[datetime]:
  match = _FILENAME_STAMP_RE.search(os.path.basename(name or ""))
  if not match:
    return None
  try:
    return datetime.strptime(match.group(1), _FILENAME_STAMP_FORMAT)
  except Exception:
    return None


def _table_exists(cur, table: str) -> bool:
  try:
    cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
    cur.fetchall()
    return True
  except Exception:
    return False


def _recorded_delivery(cur, draft_id: str, delivery_dir: str) -> Optional[Tuple[str, str]]:
  """The authoritative tier: this draft's own delivery rows, newest first."""
  if not _table_exists(cur, TABLE_NAME):
    return None
  cur.execute(
    f"""SELECT workbook_filename, source_path, delivered_path FROM {TABLE_NAME}
        WHERE draft_id = %s ORDER BY id DESC""",
    (draft_id,),
  )
  for filename, source_path, delivered_path in (cur.fetchall() or []):
    for candidate in (delivered_path, source_path):
      if candidate and os.path.isfile(candidate):
        return (candidate, "delivery record")
    if delivery_dir and filename:
      joined = os.path.join(delivery_dir, filename)
      if os.path.isfile(joined):
        return (joined, "delivery record")
  return None


def _run_stamps_by_draft(cur, business_name: str) -> Dict[str, List[datetime]]:
  """Every planning run of every draft sharing this business name.

  Keyed by draft_id so a candidate file can be awarded to its NEAREST run
  across the whole name — the disambiguation the mtime glob never did.
  """
  # Deliberately two queries, not a JOIN: intake_consult_drafts.draft_id is
  # utf8mb4_unicode_ci and post_intake_run_diagnostics.draft_id is
  # utf8mb4_0900_ai_ci, so joining them raises 'Illegal mix of collations'.
  # Nothing here is caught and turned into an empty answer -- a lookup that
  # cannot run must fail loudly, because "no stamps" and "the query is broken"
  # would otherwise both read as "not attributable", which is the same silent
  # not-verified this whole gate exists to end.
  stamps: Dict[str, List[datetime]] = {}
  cur.execute(
    "SELECT draft_id FROM intake_consult_drafts WHERE business_name = %s",
    (business_name,),
  )
  draft_ids = [str(r[0]) for r in (cur.fetchall() or []) if r and r[0]]
  if not draft_ids:
    return stamps
  placeholders = ", ".join(["%s"] * len(draft_ids))
  cur.execute(
    f"SELECT draft_id, created_at FROM post_intake_run_diagnostics "
    f"WHERE draft_id IN ({placeholders})",
    tuple(draft_ids),
  )
  rows = cur.fetchall() or []
  for draft, created_at in rows:
    if not isinstance(created_at, datetime):
      continue
    stamps.setdefault(str(draft), []).append(created_at)
  return stamps


def resolve_workbook_for_draft(
  cur,
  draft_id: str,
  *,
  delivery_dir: str = "",
  business_name: str = "",
  window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> Dict[str, Any]:
  """Return {'path': str|None, 'basis': str, 'detail': str} for ONE draft.

  ``path`` is None whenever the file cannot be attributed to THIS draft. The
  detail always says why, so a not_applicable verdict downstream is readable
  rather than mute.
  """
  draft_id = str(draft_id or "").strip()
  delivery_dir = str(delivery_dir or "").strip()
  if not draft_id:
    return {"path": None, "basis": "none", "detail": "no draft_id"}

  recorded = _recorded_delivery(cur, draft_id, delivery_dir)
  if recorded:
    return {"path": recorded[0], "basis": recorded[1],
            "detail": f"{os.path.basename(recorded[0])} (delivery record for this draft)"}

  if not business_name:
    try:
      cur.execute(
        "SELECT business_name FROM intake_consult_drafts WHERE draft_id = %s",
        (draft_id,),
      )
      row = cur.fetchone()
      business_name = str((row[0] if row else "") or "").strip()
    except Exception:
      business_name = ""
  if not business_name:
    return {"path": None, "basis": "none", "detail": "draft carries no business name"}
  if not delivery_dir or not os.path.isdir(delivery_dir):
    return {"path": None, "basis": "none",
            "detail": "no delivered-workbook directory to read"}

  candidates = glob.glob(os.path.join(delivery_dir, f"{business_name}*.xlsx"))
  if not candidates:
    return {"path": None, "basis": "none",
            "detail": f"no delivered workbook for {business_name!r}"}

  stamps_by_draft = _run_stamps_by_draft(cur, business_name)
  mine = stamps_by_draft.get(draft_id) or []
  if not mine:
    return {"path": None, "basis": "none",
            "detail": (f"{len(candidates)} workbook(s) named {business_name!r} but this "
                       "draft has no run timestamp to bind them by")}

  best: Optional[Tuple[datetime, float, str]] = None
  contested: List[str] = []
  for path in candidates:
    stamp = _stamp_from_filename(path)
    if stamp is None:
      continue
    owner, owner_delta = None, None
    for other_draft, other_stamps in stamps_by_draft.items():
      for other_stamp in other_stamps:
        delta = abs((stamp - other_stamp).total_seconds())
        if owner_delta is None or delta < owner_delta:
          owner, owner_delta = other_draft, delta
    if owner is None or owner_delta is None or owner_delta > window_seconds:
      continue
    if owner != draft_id:
      contested.append(os.path.basename(path))
      continue
    # A draft can run more than once. Among the files that are genuinely THIS
    # draft's, the latest export is the one that reflects its current state.
    if best is None or stamp > best[0]:
      best = (stamp, owner_delta, path)

  if best is None:
    detail = (f"no workbook attributable to this draft; {len(candidates)} file(s) share "
              f"the name {business_name!r}")
    if contested:
      detail += f" and belong to other drafts ({', '.join(sorted(contested)[:3])})"
    return {"path": None, "basis": "none", "detail": detail}
  return {"path": best[2], "basis": "run window",
          "detail": (f"{os.path.basename(best[2])} (this draft's latest run, "
                     f"stamp within {best[1]:.0f}s of it)")}
