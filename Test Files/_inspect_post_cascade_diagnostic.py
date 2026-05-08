"""Read planning_run_json.target_seeking_diagnostics.post_cascade_completion
for a draft_id and print the per-step outcome of the orchestrator's
post-cascade tail.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = ROOT / "python"
CLIENT_DIR = PYTHON_DIR / "client_intake_and_finmo"
for extra in (str(PYTHON_DIR), str(CLIENT_DIR)):
  if extra not in sys.path:
    sys.path.insert(0, extra)

try:
  from dotenv import load_dotenv  # type: ignore
  env_path = ROOT / ".env"
  if env_path.exists():
    load_dotenv(env_path, override=False)
  else:
    load_dotenv(override=False)
except Exception:
  pass

import mysql.connector  # type: ignore


def _connect():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD") or "",
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or "3306"),
  )


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--draft-id", required=True)
  args = parser.parse_args()

  conn = _connect()
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
      "SELECT planning_run_json, realism_memo_json FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1",
      (args.draft_id,),
    )
    row = cur.fetchone()
    cur.close()
  finally:
    conn.close()

  if not row:
    print(f"draft_id {args.draft_id} not found")
    return 1

  planning_run_json = row.get("planning_run_json")
  if isinstance(planning_run_json, (bytes, bytearray)):
    planning_run_json = planning_run_json.decode("utf-8")
  if isinstance(planning_run_json, str):
    try:
      planning_run_json = json.loads(planning_run_json)
    except Exception:
      planning_run_json = {}
  if not isinstance(planning_run_json, dict):
    planning_run_json = {}

  realism_memo_json = row.get("realism_memo_json")
  if isinstance(realism_memo_json, (bytes, bytearray)):
    realism_memo_json = realism_memo_json.decode("utf-8")
  if isinstance(realism_memo_json, str):
    try:
      realism_memo_json = json.loads(realism_memo_json)
    except Exception:
      realism_memo_json = {}

  print("=" * 80)
  print("post_cascade_completion (top-level on planning_run_json):")
  print("=" * 80)
  pcc = planning_run_json.get("post_cascade_completion") or {}
  print(json.dumps(pcc, indent=2, default=str))

  print()
  print("=" * 80)
  print("target_seeking_diagnostics.post_cascade_completion:")
  print("=" * 80)
  tsd = planning_run_json.get("target_seeking_diagnostics") or {}
  print(json.dumps(tsd.get("post_cascade_completion") or {}, indent=2, default=str))

  print()
  print("=" * 80)
  print("realism_memo_json (top-level keys):")
  print("=" * 80)
  if isinstance(realism_memo_json, dict):
    for k in sorted(realism_memo_json.keys()):
      v = realism_memo_json[k]
      summary = type(v).__name__
      if isinstance(v, list):
        summary = f"list[{len(v)}]"
      elif isinstance(v, dict):
        summary = f"dict({len(v)} keys: {sorted(v.keys())[:5]})"
      print(f"  {k}: {summary}")
  print()
  if isinstance(realism_memo_json, dict):
    rg = realism_memo_json.get("realism_gate") or {}
    if isinstance(rg, dict):
      print("realism_memo_json.realism_gate keys:", sorted(rg.keys()))
      ll = rg.get("line_level") or {}
      if isinstance(ll, dict):
        print("  line_level keys:", sorted(ll.keys()))
        results = ll.get("results") or []
        print(f"  line_level.results count: {len(results) if isinstance(results, list) else 'NOT-A-LIST'}")
    results = realism_memo_json.get("results") or []
    print(f"  top-level results count: {len(results) if isinstance(results, list) else 'NOT-A-LIST'}")

  print()
  print("=" * 80)
  print("planning_run_json keys:")
  print("=" * 80)
  for k in sorted(planning_run_json.keys()):
    v = planning_run_json[k]
    summary = type(v).__name__
    if isinstance(v, list):
      summary = f"list[{len(v)}]"
    elif isinstance(v, dict):
      summary = f"dict({len(v)} keys)"
    print(f"  {k}: {summary}")

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
