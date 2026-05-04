from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path(
  os.getenv("CLIENT_FINANCIAL_MODELS_DIR")
  or r"C:\dev\Cilient Plans"
)


def safe_filename_part(value: object) -> str:
  text = re.sub(r'[\\/:*?"<>|]+', "", str(value or "").strip())
  text = re.sub(r"[^A-Za-z0-9 ._-]+", "", text)
  text = re.sub(r"\s+", " ", text).strip()
  return text[:180] or "client_financial_model"


def build_workbook_path(
  *,
  output_dir: Path,
  business_name: str,
  client_id: str,
  draft_id: str,
  written_at: datetime,
) -> Path:
  company = safe_filename_part(business_name)
  timestamp = written_at.strftime("%m-%d-%Y %H-%M-%S")
  return output_dir / f"{company} -- {timestamp}.xlsx"
