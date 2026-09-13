"""DELIVERED ARTIFACTS OVER THE API - so reading a plan never needs a bridge.

Cowork drives the app from the Claude app on Nick's device and files issues
through 127.0.0.1:5050. Opening the workbook it just produced was a different
channel entirely - the device's filesystem - and when that channel went down
Cowork lost the ability to read Checks!B2, inspect a written plan, or compare
two plans, for twelve runs, while every file sat healthy on disk.

These three routes put the artifact reads on the origin Cowork already uses
every run. Read-only, loopback-only, and scoped to the two delivered-artifact
folders: nothing here writes, deletes, or reaches outside those roots.

  GET /api/artifacts?kind=workbook|plan&business=&limit=
  GET /api/artifacts/workbook?file=&sheet=&cell=&cells=&formulas=
  GET /api/artifacts/plan?file=&max_chars=

Checks!B2 - the one cell every run is asked to report - is now one GET:
  /api/artifacts/workbook?file=<name>.xlsx&sheet=Checks&cell=B2
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify

logger = logging.getLogger(__name__)

#: The two delivered-artifact folders. "Cilient" is misspelled on disk and that
#: spelling is load-bearing - every delivery since August has landed there.
_DEFAULT_WORKBOOK_DIR = r"C:\dev\Cilient Plans"
_DEFAULT_PLAN_DIR = r"C:\dev\Client Written Plans"

#: Only these extensions are readable, per root. A file outside the set is a
#: 404 even when it sits in the folder - the roots hold scratch and lock files
#: (~$... from a still-open Excel) that nothing should serve.
_WORKBOOK_EXT = {".xlsx"}
_PLAN_EXT = {".docx", ".md", ".txt", ".json"}

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

#: Bounds. A delivered workbook has ~14 sheets and a written plan runs to tens
#: of thousands of characters; these caps keep one careless request from
#: returning the whole corpus.
_MAX_LIST = 500
_DEFAULT_LIST = 50
_MAX_CELLS = 20000
_DEFAULT_PLAN_CHARS = 200000
_MAX_PLAN_CHARS = 2000000


def _roots() -> Dict[str, Path]:
  return {
    "workbook": Path(os.getenv("BPA_WORKBOOK_DIR") or _DEFAULT_WORKBOOK_DIR),
    "plan": Path(os.getenv("BPA_PLAN_DIR") or _DEFAULT_PLAN_DIR),
  }


def _allowed_ext(kind: str) -> set:
  return _WORKBOOK_EXT if kind == "workbook" else _PLAN_EXT


def _is_loopback(request) -> bool:
  """Loopback only. These routes read files off the operator's disk; they have
  no business answering anything that arrived over a network interface."""
  addr = str(getattr(request, "remote_addr", "") or "").strip()
  if addr.startswith("::ffff:"):
    addr = addr[7:]
  return addr in _LOOPBACK


def _deny_remote():
  return (jsonify({"error": "forbidden", "detail": "loopback only"}), 403)


def _resolve(kind: str, rel: str) -> Tuple[Optional[Path], Optional[Any]]:
  """Resolve a client-supplied name inside its root, or return an error tuple.

  The containment check is done on the RESOLVED path (symlinks and .. already
  collapsed), so '..\\..\\.env' and an absolute path both land outside the root
  and are refused rather than read."""
  kind = (kind or "").strip().lower()
  roots = _roots()
  if kind not in roots:
    return (None, (jsonify({"error": "invalid_request", "detail": "kind must be workbook or plan"}), 400))
  rel = str(rel or "").strip().strip('"')
  if not rel:
    return (None, (jsonify({"error": "invalid_request", "detail": "file is required"}), 400))
  root = roots[kind]
  try:
    root_resolved = root.resolve()
    candidate = (root / rel).resolve()
  except (OSError, ValueError) as exc:
    return (None, (jsonify({"error": "invalid_request", "detail": f"unreadable path: {exc}"}), 400))
  if candidate != root_resolved and root_resolved not in candidate.parents:
    logger.warning("ARTIFACTS_PATH_REFUSED kind=%s rel=%r resolved=%s", kind, rel, candidate)
    return (None, (jsonify({"error": "not_found", "detail": "file is not inside the artifact folder"}), 404))
  if candidate.suffix.lower() not in _allowed_ext(kind):
    return (None, (jsonify({"error": "not_found", "detail": f"{candidate.suffix} is not a readable {kind}"}), 404))
  if not candidate.is_file():
    return (None, (jsonify({"error": "not_found", "detail": "no such file"}), 404))
  return (candidate, None)


def _describe(path: Path, root: Path, kind: str) -> Dict[str, Any]:
  stat = path.stat()
  return {
    "kind": kind,
    "file": str(path.relative_to(root)).replace("\\", "/"),
    "name": path.name,
    "bytes": stat.st_size,
    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
  }


_KNOWN_ARGS = {
  "/api/artifacts": {"kind", "business", "limit", "draft_id"},
  "/api/artifacts/workbook": {"file", "sheet", "cell", "cells", "formulas", "draft_id"},
  "/api/artifacts/plan": {"file", "max_chars", "draft_id", "render_report"},
}

#: What the routes are and how to call them. This exists because Cowork spent
#: four calls finding three endpoints, and then asked for the formula with
#: `values=formula` - a parameter this API does not have. The old code ignored
#: it silently and returned the cached value, so a wrong call and a right call
#: were indistinguishable in the answer. Unknown parameters are now a 400, and
#: this route says what the right ones are.
ROUTES = [
  {
    "route": "GET /api/artifacts",
    "does": "list delivered artifacts, newest first",
    "params": {"draft_id": "PREFERRED - both artifacts for one draft, from "
                           "the delivery record, with provenance",
               "kind": "workbook | plan (both if omitted)",
               "business": "case-insensitive substring of the filename",
               "limit": f"1-{_MAX_LIST}, default {_DEFAULT_LIST}"},
    "example": "/api/artifacts?draft_id=<draft_id>",
  },
  {
    "route": "GET /api/artifacts/workbook",
    "does": "read a delivered workbook: sheet names, one cell, or a range",
    "params": {"draft_id": "PREFERRED - the workbook this draft delivered; "
                           "proves provenance, which a filename cannot",
               "file": "NOT SUPPORTED - reading by filename is refused; a "
                       "filename cannot prove which run made a file",
               "sheet": "sheet name; omit for the sheet list",
               "cell": "one address, e.g. B2 - returns formula AND cached",
               "cells": f"a range, e.g. A1:D20 (max {_MAX_CELLS} cells)",
               "formulas": "1 to make `value` the formula; both halves are "
                           "returned either way, so you rarely need this"},
    "example": "/api/artifacts/workbook?file=<name>.xlsx&sheet=Checks&cell=B2",
    "note": "a cell read returns formula, cached, has_formula and "
            "has_cached_value - a formula with no cached value is the A-136 "
            "class and carries a warning",
  },
  {
    "route": "GET /api/artifacts/plan",
    "does": "read a written plan as text, or a render report verbatim",
    "params": {"draft_id": "PREFERRED - the plan this draft delivered",
               "file": "NOT SUPPORTED - pass draft_id",
               "max_chars": f"default {_DEFAULT_PLAN_CHARS}, max {_MAX_PLAN_CHARS}",
               "render_report": "0 to omit; on by default"},
    "example": "/api/artifacts/plan?draft_id=<draft_id>",
    "note": "the response carries render_report - attempted / placed / absent "
            "with each absent item's reason, which is where 'how many figures, "
            "did they place' is answered",
  },
]


def _reject_unknown_args(request, route: str):
  """An unknown parameter is a 400, never a silent default. `values=formula`
  returning the cached value is how a wrong call looked like a right one."""
  known = _KNOWN_ARGS.get(route, set())
  unknown = sorted(set(request.args.keys()) - known)
  if not unknown:
    return None
  return (jsonify({
    "error": "invalid_request",
    "detail": f"unknown parameter(s): {', '.join(unknown)}",
    "known_parameters": sorted(known),
    "discovery": "GET /api/artifacts/help",
  }), 400)


def get_artifacts_help_handler(*, app, request):
  """Every artifact route, its parameters and an example - one call."""
  if request.method == "OPTIONS":
    return ("", 204)
  if not _is_loopback(request):
    return _deny_remote()
  roots = _roots()
  return jsonify({
    "status": "ok",
    "purpose": "read delivered workbooks and written plans over the API, so "
               "reading an artifact never depends on the device bridge",
    "access": "read-only, loopback-only, scoped to the two folders below",
    "folders": {k: str(v) for k, v in roots.items()},
    "routes": ROUTES,
  })



# ------------------------------------------------------- draft_id keying

def _db():
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

  return get_mysql_connection()


def _delivered_for_draft(draft_id: str, kind: str = ""):
  """What this draft actually delivered, from the delivery record.

  Reading by filename cannot prove provenance: the output folders are shared
  across runs, several businesses have had similar names, and the workbook and
  the plan do not even spell the same business the same way (the workbook
  strips "&", so 'Sorrel & Dunne Cold Brew' ships as 'Sorrel Dunne Cold
  Brew'). The record is the only thing that ties a file to the run that made
  it."""
  from client_intake_and_finmo import delivered_artifacts as da  # type: ignore

  conn = _db()
  try:
    rows = da.for_draft(conn, str(draft_id).strip(), kind=kind)
    return [{**r, "verified": da.verify(r)} for r in rows]
  finally:
    try:
      conn.close()
    except Exception:
      pass


def _resolve_by_draft(draft_id: str, kind: str):
  """The newest delivered artifact of one kind for one draft, as a path inside
  its root - or an error tuple saying precisely why not."""
  rows = _delivered_for_draft(draft_id, kind=kind)
  if not rows:
    return (None, None, (jsonify({
      "error": "not_found",
      "detail": f"no {kind} recorded for draft {draft_id}",
      "note": "the delivery record starts from 2026-09-13; files delivered "
              "before it cannot be mapped to a draft and must be read by name",
    }), 404))
  row = rows[0]
  path = Path(str(row.get("path") or ""))
  roots = _roots()
  try:
    root_resolved = roots[kind if kind in roots else "workbook"].resolve()
    resolved = path.resolve()
  except (OSError, ValueError, KeyError):
    return (None, row, (jsonify({"error": "unreadable", "detail": "recorded path is unreadable"}), 422))
  if resolved != root_resolved and root_resolved not in resolved.parents:
    return (None, row, (jsonify({
      "error": "not_found",
      "detail": "the recorded path is outside the artifact folder",
    }), 404))
  if not resolved.is_file():
    return (None, row, (jsonify({
      "error": "not_found",
      "detail": "the recorded file is no longer on disk",
      "recorded": {k: str(v) for k, v in row.items() if k != "verified"},
    }), 404))
  return (resolved, row, None)


def _provenance(row) -> Dict[str, Any]:
  """What the caller needs to know that a filename cannot tell it."""
  verified = (row or {}).get("verified") or {}
  out = {
    "draft_id": (row or {}).get("draft_id"),
    "planning_run_id": (row or {}).get("planning_run_id"),
    "delivered_at": str((row or {}).get("delivered_at") or ""),
    "bytes": (row or {}).get("bytes"),
    "sha256": (row or {}).get("sha256"),
    "state": verified.get("state"),
  }
  if verified.get("state") == "replaced":
    out["warning"] = ("the file on disk no longer matches what was recorded - "
                      "a later run wrote over this path")
  return out


# ---------------------------------------------------------------- list

def get_artifacts_handler(*, app, request):
  """What has been delivered. Newest first, so `limit=1` is the run that just
  finished."""
  if request.method == "OPTIONS":
    return ("", 204)
  if not _is_loopback(request):
    return _deny_remote()
  bad = _reject_unknown_args(request, "/api/artifacts")
  if bad:
    return bad

  kind = str(request.args.get("kind") or "").strip().lower()
  kinds = [kind] if kind in ("workbook", "plan") else ["workbook", "plan"]
  if kind and kind not in ("workbook", "plan"):
    return (jsonify({"error": "invalid_request", "detail": "kind must be workbook or plan"}), 400)

  # BY DRAFT (Cowork spec 4): both artifacts for one draft with their
  # timestamps, so a fresh build is distinguishable from a stale file sitting
  # in the same folder under a similar name.
  draft_id = str(request.args.get("draft_id") or "").strip()
  if draft_id:
    rows = _delivered_for_draft(draft_id, kind=kind if kind in ("workbook", "plan") else "")
    return jsonify({
      "status": "ok",
      "draft_id": draft_id,
      "count": len(rows),
      "artifacts": [{
        "kind": r.get("kind"),
        "name": r.get("name"),
        "path": r.get("path"),
        **_provenance(r),
      } for r in rows],
      "note": None if rows else
              "nothing recorded for this draft - the delivery record starts "
              "2026-09-13; earlier files must be read by name",
    })

  business = str(request.args.get("business") or "").strip().lower()
  try:
    limit = int(request.args.get("limit") or _DEFAULT_LIST)
  except (TypeError, ValueError):
    return (jsonify({"error": "invalid_request", "detail": "limit must be an integer"}), 400)
  limit = max(1, min(limit, _MAX_LIST))

  roots = _roots()
  rows: List[Dict[str, Any]] = []
  missing: List[str] = []
  for k in kinds:
    root = roots[k]
    if not root.is_dir():
      missing.append(f"{k}: {root}")
      continue
    root_resolved = root.resolve()
    for path in root.rglob("*"):
      if not path.is_file() or path.suffix.lower() not in _allowed_ext(k):
        continue
      if path.name.startswith("~$"):
        continue   # an Excel lock file for a workbook someone still has open
      if business and business not in path.name.lower():
        continue
      try:
        rows.append(_describe(path, root_resolved, k))
      except (OSError, ValueError):
        continue
  rows.sort(key=lambda r: r["modified"], reverse=True)
  body: Dict[str, Any] = {"status": "ok", "count": len(rows), "artifacts": rows[:limit]}
  if len(rows) > limit:
    body["truncated"] = True
    body["detail"] = f"{len(rows)} matched, {limit} returned - raise limit or filter by business"
  if missing:
    body["folders_missing"] = missing
  return jsonify(body)


# ------------------------------------------------------------ workbook

def _cell_value(cell) -> Any:
  value = cell.value
  if isinstance(value, datetime):
    return value.isoformat(timespec="seconds")
  return value


def _companion_value(path: Path, sheet: str, cell: str, *, formulas: bool):
  """The other half of the pair: the cached value when we read formulas, the
  formula when we read values. openpyxl can only do one per load, so this is a
  second open of the same file - cheap next to being unable to tell a live
  workbook from a blank one."""
  try:
    import openpyxl  # type: ignore

    wb = openpyxl.load_workbook(str(path), data_only=formulas, read_only=True)
    try:
      if sheet not in wb.sheetnames:
        return None
      return _cell_value(wb[sheet][cell])
    finally:
      try:
        wb.close()
      except Exception:
        pass
  except Exception as exc:  # noqa: BLE001
    logger.warning("ARTIFACTS_COMPANION_READ_FAILED %s!%s: %s", sheet, cell, exc)
    return None


def get_artifact_workbook_handler(*, app, request):
  """Read a delivered workbook.

  No sheet  -> the sheet names.
  sheet     -> that sheet's dimensions (and, with cell/cells, its values).
  cell=B2   -> one value.
  cells=A1:D20 -> a bounded 2-D block.
  formulas=1   -> the stored formulas instead of the cached values. The
                  distinction is the whole of A-136: a workbook can carry
                  perfect formulas and no cached values, and then every
                  reader without a spreadsheet engine sees blanks."""
  if request.method == "OPTIONS":
    return ("", 204)
  if not _is_loopback(request):
    return _deny_remote()
  bad = _reject_unknown_args(request, "/api/artifacts/workbook")
  if bad:
    return bad

  draft_id = str(request.args.get("draft_id") or "").strip()
  record = None
  if draft_id:
    if request.args.get("file"):
      return (jsonify({"error": "invalid_request",
                       "detail": "pass draft_id OR file, not both - they can disagree"}), 400)
    path, record, err = _resolve_by_draft(draft_id, "workbook")
    if err:
      return err
  else:
    # FILENAME READS ARE REFUSED (Nick 2026-09-13): "refused once draft_id
    # keying lands, not labelled". A caveat on something that still works gets
    # ignored, and a playbook keeps the path it already has. The folders are
    # shared across runs, two workbooks for one business has already happened,
    # and the workbook strips "&" so the two artifacts of one business do not
    # even share a name - a filename cannot prove which run made a file, so it
    # is not an acceptable way to read one.
    return (jsonify({
      "error": "invalid_request",
      "detail": "reading by filename is not supported - pass draft_id",
      "why": "a filename cannot prove which run produced a file; the output "
             "folders are shared across runs and similar business names have "
             "already collided",
      "how": "GET /api/artifacts?draft_id=<draft_id> lists what that draft "
             "delivered; pass the same draft_id here",
      "note": "artifacts delivered before 2026-09-13 have no record and "
              "cannot be read by this route - 926 workbooks and the written "
              "plans whose run folders carry no run id",
    }), 400)

  sheet = str(request.args.get("sheet") or "").strip()
  cell = str(request.args.get("cell") or "").strip()
  cells = str(request.args.get("cells") or "").strip()
  formulas = str(request.args.get("formulas") or "").strip().lower() in ("1", "true", "yes")

  try:
    import openpyxl  # type: ignore
  except Exception as exc:  # pragma: no cover
    logger.exception("openpyxl unavailable: %s", exc)
    return (jsonify({"error": "server_error", "detail": "openpyxl is not installed"}), 500)

  try:
    wb = openpyxl.load_workbook(str(path), data_only=not formulas, read_only=True)
  except Exception as exc:  # noqa: BLE001
    logger.warning("ARTIFACTS_WORKBOOK_UNREADABLE %s: %s", path.name, exc)
    return (jsonify({"error": "unreadable", "detail": f"{type(exc).__name__}: {exc}"}), 422)

  try:
    base: Dict[str, Any] = {
      "status": "ok",
      "provenance": _provenance(record) if record else
                    {"state": "unkeyed", "note": "read by filename - provenance "
                     "unproven; pass draft_id to read the recorded delivery"},
      "file": path.name,
      "bytes": path.stat().st_size,
      "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
      "values": "formulas" if formulas else "cached",
      "sheets": list(wb.sheetnames),
    }
    if not sheet:
      return jsonify(base)
    if sheet not in wb.sheetnames:
      return (jsonify({"error": "not_found", "detail": f"no sheet {sheet!r}", "sheets": list(wb.sheetnames)}), 404)

    ws = wb[sheet]
    base["sheet"] = sheet
    base["dimensions"] = ws.calculate_dimension()
    base["max_row"] = ws.max_row
    base["max_column"] = ws.max_column

    if cell:
      try:
        target = ws[cell]
      except (ValueError, KeyError, TypeError) as exc:
        return (jsonify({"error": "invalid_request", "detail": f"bad cell {cell!r}: {exc}"}), 400)
      if isinstance(target, tuple):
        return (jsonify({"error": "invalid_request", "detail": "cell takes one address; use cells for a range"}), 400)
      base["cell"] = cell
      base["value"] = _cell_value(target)
      # BOTH HALVES, ALWAYS (Cowork spec, 2026-09-13). "Does this workbook
      # carry calculated values or only formulas" is the standing question and
      # it cannot be answered by a single resolved value. A formula WITH a
      # cached OK is a healthy sheet; a formula with `cached: null` is A-136,
      # where every reader without a spreadsheet engine sees blanks. Returning
      # both removes the mode parameter that had to be guessed right.
      other = _companion_value(path, sheet, cell, formulas=formulas)
      base["formula"] = base["value"] if formulas else other
      base["cached"] = other if formulas else base["value"]
      base["has_formula"] = isinstance(base["formula"], str) and str(base["formula"]).startswith("=")
      base["has_cached_value"] = base["cached"] is not None
      if base["has_formula"] and not base["has_cached_value"]:
        base["warning"] = ("formula present with no cached value - every reader without a "
                           "spreadsheet engine sees a blank here (the A-136 class)")
      return jsonify(base)

    if cells:
      try:
        block = ws[cells]
      except (ValueError, KeyError, TypeError) as exc:
        return (jsonify({"error": "invalid_request", "detail": f"bad range {cells!r}: {exc}"}), 400)
      if not isinstance(block, tuple):
        block = ((block,),)
      rows: List[List[Any]] = []
      seen = 0
      for row in block:
        row_tuple = row if isinstance(row, tuple) else (row,)
        seen += len(row_tuple)
        if seen > _MAX_CELLS:
          base["truncated"] = True
          base["detail"] = f"range exceeds {_MAX_CELLS} cells"
          break
        rows.append([_cell_value(c) for c in row_tuple])
      base["cells"] = cells
      base["rows"] = rows
      return jsonify(base)

    return jsonify(base)
  finally:
    try:
      wb.close()
    except Exception:
      pass


# ---------------------------------------------------------------- plan

def _docx_text(path: Path, max_chars: int) -> Tuple[str, bool, Dict[str, int]]:
  """The written plan as readable text: paragraphs in order, then each table
  row as tab-separated cells. Enough to inspect a section, quote it back in an
  issue, or diff two plans against each other."""
  import docx  # type: ignore

  document = docx.Document(str(path))
  parts: List[str] = []
  total = 0
  truncated = False
  counts = {"paragraphs": 0, "tables": 0, "table_rows": 0}

  for para in document.paragraphs:
    text = (para.text or "").strip()
    counts["paragraphs"] += 1
    if not text:
      continue
    if total + len(text) > max_chars:
      truncated = True
      break
    parts.append(text)
    total += len(text) + 1

  if not truncated:
    for table in document.tables:
      counts["tables"] += 1
      for row in table.rows:
        counts["table_rows"] += 1
        line = "\t".join((c.text or "").strip() for c in row.cells)
        if not line.strip():
          continue
        if total + len(line) > max_chars:
          truncated = True
          break
        parts.append(line)
        total += len(line) + 1
      if truncated:
        break

  return ("\n".join(parts), truncated, counts)



def _render_report_for(plan_path: Path, draft_id: str = "") -> Dict[str, Any]:
  """The renderer's own account of the plan beside it: every registry item it
  attempted, whether it placed, and the reason when it did not.

  Looked up by the delivery record first (that is what ties it to the run),
  then by the sidecar convention `<plan>.docx.render_report.json`."""
  import json

  candidate: Optional[Path] = None
  if draft_id:
    for row in _delivered_for_draft(draft_id, kind="render_report"):
      maybe = Path(str(row.get("path") or ""))
      if maybe.is_file():
        candidate = maybe
        break
  if candidate is None:
    sidecar = Path(str(plan_path) + ".render_report.json")
    if sidecar.is_file():
      candidate = sidecar
  if candidate is None:
    return {"available": False,
            "detail": "no render report recorded or beside this plan"}
  try:
    items = json.loads(candidate.read_text(encoding="utf-8"))
  except (OSError, ValueError) as exc:
    return {"available": False, "detail": f"unreadable: {exc}"}
  if not isinstance(items, list):
    return {"available": False, "detail": "unexpected shape"}
  placed = [i for i in items if isinstance(i, dict) and i.get("placed")]
  absent = [i for i in items if isinstance(i, dict) and not i.get("placed")]
  return {
    "available": True,
    "source": candidate.name,
    "attempted": len(items),
    "placed": len(placed),
    "absent": len(absent),
    "absent_items": [{"id": i.get("id"), "reason": i.get("reason")} for i in absent],
    "placed_ids": [i.get("id") for i in placed],
  }


def get_artifact_plan_handler(*, app, request):
  """Read a delivered written plan as text (.docx), or a sidecar (.json/.md/
  .txt) verbatim - the render reports live beside the plans and say what the
  writer did."""
  if request.method == "OPTIONS":
    return ("", 204)
  if not _is_loopback(request):
    return _deny_remote()
  bad = _reject_unknown_args(request, "/api/artifacts/plan")
  if bad:
    return bad

  draft_id = str(request.args.get("draft_id") or "").strip()
  record = None
  if draft_id:
    if request.args.get("file"):
      return (jsonify({"error": "invalid_request",
                       "detail": "pass draft_id OR file, not both - they can disagree"}), 400)
    path, record, err = _resolve_by_draft(draft_id, "plan")
    if err:
      return err
  else:
    # FILENAME READS ARE REFUSED (Nick 2026-09-13): "refused once draft_id
    # keying lands, not labelled". A caveat on something that still works gets
    # ignored, and a playbook keeps the path it already has. The folders are
    # shared across runs, two workbooks for one business has already happened,
    # and the workbook strips "&" so the two artifacts of one business do not
    # even share a name - a filename cannot prove which run made a file, so it
    # is not an acceptable way to read one.
    return (jsonify({
      "error": "invalid_request",
      "detail": "reading by filename is not supported - pass draft_id",
      "why": "a filename cannot prove which run produced a file; the output "
             "folders are shared across runs and similar business names have "
             "already collided",
      "how": "GET /api/artifacts?draft_id=<draft_id> lists what that draft "
             "delivered; pass the same draft_id here",
      "note": "artifacts delivered before 2026-09-13 have no record and "
              "cannot be read by this route - 926 workbooks and the written "
              "plans whose run folders carry no run id",
    }), 400)

  try:
    max_chars = int(request.args.get("max_chars") or _DEFAULT_PLAN_CHARS)
  except (TypeError, ValueError):
    return (jsonify({"error": "invalid_request", "detail": "max_chars must be an integer"}), 400)
  max_chars = max(1, min(max_chars, _MAX_PLAN_CHARS))

  stat = path.stat()
  base: Dict[str, Any] = {
    "status": "ok",
    "provenance": _provenance(record) if record else
                  {"state": "unkeyed", "note": "read by filename - provenance "
                   "unproven; pass draft_id to read the recorded delivery"},
    "file": path.name,
    "bytes": stat.st_size,
    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
  }

  if path.suffix.lower() == ".docx":
    try:
      text, truncated, counts = _docx_text(path, max_chars)
    except Exception as exc:  # noqa: BLE001
      logger.warning("ARTIFACTS_PLAN_UNREADABLE %s: %s", path.name, exc)
      return (jsonify({"error": "unreadable", "detail": f"{type(exc).__name__}: {exc}"}), 422)
    base.update({"format": "docx", "chars": len(text), "text": text, **counts})
    if truncated:
      base["truncated"] = True
      base["detail"] = f"cut at max_chars={max_chars}"
    # THE RENDER REPORT ALONGSIDE THE TEXT (Cowork spec 3). "How many figures,
    # and did they place" is a question about the plan that the plan's own text
    # cannot answer - the renderer's account is where placed true/false lives.
    if str(request.args.get("render_report") or "1").strip().lower() not in ("0", "false", "no"):
      base["render_report"] = _render_report_for(path, draft_id)
    return jsonify(base)

  try:
    raw = path.read_text(encoding="utf-8", errors="replace")
  except OSError as exc:
    return (jsonify({"error": "unreadable", "detail": str(exc)}), 422)
  truncated = len(raw) > max_chars
  base.update({"format": path.suffix.lower().lstrip("."), "chars": len(raw), "text": raw[:max_chars]})
  if truncated:
    base["truncated"] = True
    base["detail"] = f"cut at max_chars={max_chars}"
  return jsonify(base)
