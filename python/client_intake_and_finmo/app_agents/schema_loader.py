from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def schema_path(file_name: str) -> Path:
  return SCHEMAS_DIR / str(file_name or "").strip()


def load_schema(file_name: str) -> Dict[str, Any]:
  path = schema_path(file_name)
  return json.loads(path.read_text(encoding="utf-8"))

