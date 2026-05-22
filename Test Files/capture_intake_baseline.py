"""Capture an intake-complete draft's structured JSON into a baseline snapshot.

A baseline snapshot is the reusable, GPT-free scaffold the intake-bypass runner
overlays scenario overrides onto. Run this once per business shape you want to
test (e.g. a bakery, an airline, a logistics firm), pointing it at a real
draft that already finished intake (active_focus='done').

Usage:
  python "Test Files/capture_intake_baseline.py" --draft-id <draft_id> --name sunny_glaze_donuts
  python "Test Files/capture_intake_baseline.py" --client-id <client_id> --name skyward_airline
  python "Test Files/capture_intake_baseline.py" --list        # list candidate drafts
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


THIS_DIR = Path(__file__).resolve().parent


def _load_common():
  spec = importlib.util.spec_from_file_location(
    "intake_bypass_common", str(THIS_DIR / "intake_bypass_common.py")
  )
  if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load intake_bypass_common.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


C = _load_common()


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def _list_candidates(conn) -> int:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT draft_id, client_id, business_name, status, active_focus, updated_at
      FROM intake_consult_drafts
      WHERE active_focus = 'done'
        AND operating_model_json IS NOT NULL
        AND financials_json IS NOT NULL
      ORDER BY updated_at DESC
      LIMIT 40
      """
    )
    rows = cur.fetchall() or []
  finally:
    cur.close()
  print(f"Intake-complete drafts available as baselines ({len(rows)}):")
  for r in rows:
    print(
      f"  {(_string(r.get('business_name')) or '(no name)'):40} "
      f"draft={r.get('draft_id')} client={r.get('client_id')} "
      f"status={r.get('status')} updated={r.get('updated_at')}"
    )
  return 0


def _select_row(conn, *, draft_id: str = "", client_id: str = "") -> Dict[str, Any]:
  cur = conn.cursor(dictionary=True)
  try:
    if draft_id:
      cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s LIMIT 1", (draft_id,))
    else:
      cur.execute("SELECT * FROM intake_consult_drafts WHERE client_id=%s LIMIT 1", (client_id,))
    row = cur.fetchone()
  finally:
    cur.close()
  if not isinstance(row, dict) or not row:
    raise RuntimeError(f"No draft found for draft_id={draft_id!r} client_id={client_id!r}")
  return row


def _build_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
  flat: Dict[str, Any] = {}
  for sql_col, key in C.BASELINE_FLAT_COLUMNS:
    flat[key] = _string(row.get(sql_col)) or None

  structured: Dict[str, Any] = {}
  for col in C.BASELINE_JSON_COLUMNS:
    structured[col] = C.parse_json(row.get(col))

  return {
    "_meta": {
      "source_draft_id": _string(row.get("draft_id")),
      "source_client_id": _string(row.get("client_id")),
      "business_name": _string(row.get("business_name")),
      "captured_at": datetime.now(timezone.utc).isoformat(),
      "note": "Structured intake output captured for the intake-bypass runner. Safe to edit by hand.",
    },
    "flat": flat,
    "structured": structured,
  }


def main(argv: Optional[list] = None) -> int:
  parser = argparse.ArgumentParser(description="Capture an intake baseline snapshot from MySQL.")
  parser.add_argument("--draft-id", default="")
  parser.add_argument("--client-id", default="")
  parser.add_argument("--name", default="", help="Output snapshot name (file becomes <name>.json).")
  parser.add_argument("--baselines-dir", default=str(C.DEFAULT_BASELINES_DIR))
  parser.add_argument("--list", action="store_true", help="List candidate intake-complete drafts and exit.")
  args = parser.parse_args(argv)

  C.load_env()
  conn = C.mysql_connect()
  try:
    if args.list:
      return _list_candidates(conn)

    draft_id = _string(args.draft_id)
    client_id = _string(args.client_id)
    if not draft_id and not client_id:
      parser.error("Provide --draft-id or --client-id (or --list).")

    row = _select_row(conn, draft_id=draft_id, client_id=client_id)
    if _string(row.get("active_focus")).lower() != "done":
      raise RuntimeError(
        f"Source draft is not intake-complete (active_focus={_string(row.get('active_focus')) or 'missing'})."
      )

    name = _string(args.name)
    if not name:
      base = _string(row.get("business_name")) or "baseline"
      name = "".join(ch.lower() if ch.isalnum() else "_" for ch in base).strip("_")
      name = "_".join(filter(None, name.split("_")))

    snapshot = _build_snapshot(row)
    missing = [k for k in ("operating_model_json", "people_json", "financials_json") if not snapshot["structured"].get(k)]
    if missing:
      raise RuntimeError(f"Source draft is missing required structured payloads: {missing}")

    baselines_dir = Path(args.baselines_dir)
    baselines_dir.mkdir(parents=True, exist_ok=True)
    out_path = baselines_dir / f"{name}.json"
    with open(out_path, "w", encoding="utf-8") as handle:
      json.dump(snapshot, handle, indent=2, ensure_ascii=False, default=str)

    size_kb = out_path.stat().st_size / 1024.0
    print(f"Captured baseline {name!r} from draft {snapshot['_meta']['source_draft_id']}")
    print(f"  Business: {snapshot['_meta']['business_name']}")
    print(f"  Wrote: {out_path}  ({size_kb:.1f} KB)")
    return 0
  finally:
    try:
      conn.close()
    except Exception:
      pass


if __name__ == "__main__":
  raise SystemExit(main())
