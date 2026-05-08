"""Phase 8 gate driver — runs verify_run_acceptance against a persisted draft
without requiring the API server to be restarted. Used to validate the
gate's check logic against an existing run's persisted state.
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

from client_intake_and_finmo.post_intake_acceptance import verify_run_acceptance  # type: ignore


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
  parser.add_argument("--planning-run-id", default="")
  args = parser.parse_args()

  conn = _connect()
  try:
    verdict = verify_run_acceptance(
      conn,
      draft_id=args.draft_id,
      planning_run_id=args.planning_run_id or None,
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass

  print(json.dumps(verdict, indent=2, default=str))
  return 0 if verdict.get("passed") else 1


if __name__ == "__main__":
  raise SystemExit(main())
