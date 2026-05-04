from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:
  from dotenv import load_dotenv  # type: ignore
except Exception:
  load_dotenv = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))

from .config import DEFAULT_OUTPUT_DIR, build_workbook_path
from .data import draft_data_from_row
from .workbook_builder import build_client_financial_model_workbook


def _load_env() -> None:
  if load_dotenv is None:
    return
  env_path = ROOT / ".env"
  try:
    if env_path.exists():
      load_dotenv(env_path, override=False)
    else:
      load_dotenv(override=False)
  except Exception:
    pass


def _select_draft_row(conn, *, draft_id: str = "", client_id: str = "") -> Dict[str, Any]:
  draft_id = str(draft_id or "").strip()
  client_id = str(client_id or "").strip()
  if not draft_id and not client_id:
    raise RuntimeError("Provide draft_id or client_id.")
  cur = conn.cursor(dictionary=True)
  try:
    if draft_id:
      cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1", (draft_id,))
    else:
      cur.execute("SELECT * FROM intake_consult_drafts WHERE client_id = %s ORDER BY updated_at DESC LIMIT 1", (client_id,))
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not isinstance(row, dict) or not row:
    raise RuntimeError("Draft not found for workbook export.")
  return row


def export_workbook_for_row(
  row: Dict[str, Any],
  *,
  output_dir: Optional[Path] = None,
  written_at: Optional[datetime] = None,
) -> Path:
  data = draft_data_from_row(row)
  target_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
  target_dir.mkdir(parents=True, exist_ok=True)
  stamp = written_at or datetime.now()
  target_path = build_workbook_path(
    output_dir=target_dir,
    business_name=data.business_name,
    client_id=data.client_id,
    draft_id=data.draft_id,
    written_at=stamp,
  )
  wb = build_client_financial_model_workbook(data)
  with tempfile.TemporaryDirectory(prefix="client_financial_model_") as temp_dir:
    temp_path = Path(temp_dir) / target_path.name
    wb.save(temp_path)
    shutil.copyfile(temp_path, target_path)
  return target_path


def export_workbook_for_draft_id(
  *,
  draft_id: str = "",
  client_id: str = "",
  output_dir: Optional[Path] = None,
  conn: Any = None,
) -> Path:
  _load_env()
  owns_connection = conn is None
  if conn is None:
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

    conn = get_mysql_connection()
  try:
    row = _select_draft_row(conn, draft_id=draft_id, client_id=client_id)
    return export_workbook_for_row(row, output_dir=output_dir)
  finally:
    if owns_connection and conn is not None:
      try:
        conn.close()
      except Exception:
        pass


def main(argv: Optional[list[str]] = None) -> int:
  parser = argparse.ArgumentParser(description="Export a completed client financial model workbook.")
  parser.add_argument("--draft-id", default="")
  parser.add_argument("--client-id", default="")
  parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
  args = parser.parse_args(argv)
  path = export_workbook_for_draft_id(
    draft_id=str(args.draft_id or "").strip(),
    client_id=str(args.client_id or "").strip(),
    output_dir=Path(args.output_dir),
  )
  print(path)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
