"""Phase 8 P1 diagnostic: invoke validate_industry_realism_bands
directly against a persisted draft's state to see what it returns.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
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


def _parse(value):
  if isinstance(value, (bytes, bytearray)):
    value = value.decode("utf-8")
  if isinstance(value, str):
    try:
      return json.loads(value)
    except Exception:
      return {}
  return value if isinstance(value, dict) else {}


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--draft-id", required=True)
  args = parser.parse_args()

  conn = _connect()
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
      "SELECT model_input_json, finmo_json, operating_model_json, financials_json FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1",
      (args.draft_id,),
    )
    row = cur.fetchone()
    cur.close()
  finally:
    conn.close()

  if not row:
    print("draft not found")
    return 1

  model_input_json = _parse(row.get("model_input_json"))
  finmo_json = _parse(row.get("finmo_json"))
  ops_json = _parse(row.get("operating_model_json"))
  financials_json = _parse(row.get("financials_json"))

  business_naics_6 = ""
  if isinstance(ops_json, dict):
    business_naics_6 = "".join(
      ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
    )

  print("model_input_json keys:", sorted(model_input_json.keys())[:10])
  print("finmo_json keys:", sorted(finmo_json.keys())[:10])
  print("finmo quarter_rows count:", len(finmo_json.get("quarter_rows") or []))
  print("ops_json keys:", sorted(ops_json.keys())[:10])
  print("business_naics_6:", repr(business_naics_6))
  print()

  from client_intake_and_finmo.post_intake_realism import validate_industry_realism_bands  # type: ignore

  try:
    result = validate_industry_realism_bands(
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      business_naics_6=business_naics_6 or None,
      ops_json=ops_json,
      financials_json=financials_json,
      planning_mode="growth",
    )
  except Exception as exc:
    print("EXCEPTION:", type(exc).__name__, str(exc)[:600])
    traceback.print_exc()
    return 2

  print("=" * 60)
  print("validate_industry_realism_bands return value:")
  print("=" * 60)
  print(json.dumps(result, indent=2, default=str)[:8000])
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
