from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
  from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
  load_dotenv = None  # type: ignore

from openpyxl import load_workbook

DEFAULT_STATE_PATH = (
  Path(__file__).resolve().parent / "temp" / "latest_intake.json"
)


def _maybe_load_dotenv() -> None:
  if load_dotenv is None:
    return
  try:
    load_dotenv()
  except Exception:
    pass


def _require_finmo_path(finmo_path: Optional[str] = None) -> str:
  if finmo_path is not None and str(finmo_path).strip():
    return str(finmo_path).strip()

  _maybe_load_dotenv()
  env_path = os.getenv("FINMO")
  if not env_path or not str(env_path).strip():
    raise RuntimeError("FINMO environment variable is not set.")
  return str(env_path).strip()


def _write_named_cell(wb, name: str, value: Any) -> None:
  if name not in wb.defined_names:
    raise KeyError(f"Named range not found in workbook: {name}")

  defined_name = wb.defined_names[name]
  destinations = list(defined_name.destinations)
  if not destinations:
    raise ValueError(f"Named range has no destinations: {name}")

  sheet_name, cell = destinations[0]
  ws = wb[sheet_name]
  ws[cell] = value


def record_latest_intake(
  *,
  current_revenue: float,
  state_path: Path = DEFAULT_STATE_PATH,
  extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  state_path.parent.mkdir(parents=True, exist_ok=True)

  payload: Dict[str, Any] = {
    "current_revenue": float(current_revenue),
    "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
  }
  if extra:
    payload.update(extra)

  state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
  return payload


def read_latest_intake(
  *, state_path: Path = DEFAULT_STATE_PATH
) -> Dict[str, Any]:
  if not state_path.exists():
    raise FileNotFoundError(
      f"Latest intake state not found at {state_path}. Submit the intake form first."
    )
  data = json.loads(state_path.read_text(encoding="utf-8"))
  if not isinstance(data, dict):
    raise ValueError(f"Invalid latest intake state at {state_path}.")
  return data


def read_intake_submission_from_db(*, client_id: str) -> Dict[str, Any]:
  _maybe_load_dotenv()
  try:
    from intake_submission import get_mysql_connection  # type: ignore
  except Exception as exc:
    raise RuntimeError("Unable to import MySQL helper get_mysql_connection.") from exc

  if not client_id or not str(client_id).strip():
    raise ValueError("client_id is required to load an intake submission.")

  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        """
        SELECT id, client_id, current_revenue, finmo_path, created_at
        FROM intake_submissions
        WHERE client_id = %s
        LIMIT 1
        """
        ,
        (str(client_id).strip(),),
      )
      row = cur.fetchone()
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass

  if not row:
    raise RuntimeError(f"No intake submission found for client_id={client_id!r}.")
  if not isinstance(row, dict):
    raise RuntimeError("Unexpected DB row shape for intake submission.")
  return row


def write_starting_revenue_intake_to_finmo(
  *,
  current_revenue: float,
  finmo_path: Optional[str] = None,
) -> Dict[str, Any]:
  finmo_path = _require_finmo_path(finmo_path)
  wb = load_workbook(finmo_path)
  _write_named_cell(wb, "starting_revenue_intake", float(current_revenue))
  wb.save(finmo_path)
  return {
    "finmo_path": finmo_path,
    "starting_revenue_intake": float(current_revenue),
  }


def sync_intake_revenue_to_finmo(
  *,
  client_id: str,
) -> Dict[str, Any]:
  submission = read_intake_submission_from_db(client_id=client_id)

  revenue = submission.get("current_revenue", None)
  if revenue is None:
    raise ValueError("Intake submission is missing current_revenue.")
  try:
    revenue_value = float(revenue)
  except Exception as exc:
    raise ValueError(
      f"Latest intake current_revenue is not numeric: {revenue}"
    ) from exc

  submission_finmo_path = submission.get("finmo_path")
  if not submission_finmo_path or not str(submission_finmo_path).strip():
    raise ValueError("Intake submission is missing finmo_path.")

  result = write_starting_revenue_intake_to_finmo(
    current_revenue=revenue_value,
    finmo_path=str(submission_finmo_path).strip(),
  )
  return {"intake_submission": submission, **result}


if __name__ == "__main__":  # pragma: no cover
  # Manual utility: write a specific submission's revenue into its FINMO workbook.
  arg_client_id = sys.argv[1] if len(sys.argv) > 1 else os.getenv("CLIENT_ID")
  if not arg_client_id:
    raise SystemExit("Usage: python finmo_revenue.py <client_id> (or set CLIENT_ID)")
  print(sync_intake_revenue_to_finmo(client_id=arg_client_id))
