from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def repo_root_from_here() -> Path:
  return Path(__file__).resolve().parent.parent


def ensure_repo_python_path(repo_root: Path) -> None:
  python_dir = str((repo_root / "python").resolve())
  if python_dir not in sys.path:
    sys.path.insert(0, python_dir)


def load_dotenv_fallback(repo_root: Path) -> None:
  env_path = repo_root / ".env"
  if not env_path.exists():
    return
  for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def json_loads_dict(raw: Any) -> Dict[str, Any]:
  if isinstance(raw, dict):
    return dict(raw)
  if raw is None:
    return {}
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def write_json(path: Path, payload: Dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text, encoding="utf-8")


def quarter_label(index: int) -> str:
  return f"Q{max(1, int(index))}"


def safe_float(value: Any) -> Optional[float]:
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return float(number)


def classify_cash_shape(values: Iterable[float]) -> str:
  seq = [float(item) for item in values if safe_float(item) is not None]
  if len(seq) < 3:
    return "unknown"
  diffs = [seq[idx] - seq[idx - 1] for idx in range(1, len(seq))]
  if all(diff >= 0 for diff in diffs):
    if len([diff for diff in diffs if diff <= 0.01]) >= max(1, len(diffs) // 3):
      return "partial_flat"
    return "staircase"
  has_negative = any(diff < 0 for diff in diffs)
  has_rebound = any(diffs[idx - 1] < 0 and diffs[idx] > 0 for idx in range(1, len(diffs)))
  if has_negative and has_rebound:
    return "rebuild"
  if has_negative:
    return "dip"
  return "mixed"


def first_match(patterns: Iterable[str], text: str) -> Optional[str]:
  for pattern in patterns:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if match:
      return match.group(1) if match.groups() else match.group(0)
  return None


def utcish_timestamp() -> str:
  return datetime.now().strftime("%Y%m%d-%H%M%S")
