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


# ---------------------------------------------------------------- list

def get_artifacts_handler(*, app, request):
  """What has been delivered. Newest first, so `limit=1` is the run that just
  finished."""
  if request.method == "OPTIONS":
    return ("", 204)
  if not _is_loopback(request):
    return _deny_remote()

  kind = str(request.args.get("kind") or "").strip().lower()
  kinds = [kind] if kind in ("workbook", "plan") else ["workbook", "plan"]
  if kind and kind not in ("workbook", "plan"):
    return (jsonify({"error": "invalid_request", "detail": "kind must be workbook or plan"}), 400)

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

  path, err = _resolve("workbook", request.args.get("file"))
  if err:
    return err

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


def get_artifact_plan_handler(*, app, request):
  """Read a delivered written plan as text (.docx), or a sidecar (.json/.md/
  .txt) verbatim - the render reports live beside the plans and say what the
  writer did."""
  if request.method == "OPTIONS":
    return ("", 204)
  if not _is_loopback(request):
    return _deny_remote()

  path, err = _resolve("plan", request.args.get("file"))
  if err:
    return err

  try:
    max_chars = int(request.args.get("max_chars") or _DEFAULT_PLAN_CHARS)
  except (TypeError, ValueError):
    return (jsonify({"error": "invalid_request", "detail": "max_chars must be an integer"}), 400)
  max_chars = max(1, min(max_chars, _MAX_PLAN_CHARS))

  stat = path.stat()
  base: Dict[str, Any] = {
    "status": "ok",
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
