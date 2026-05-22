"""Shared helpers for the intake-bypass tooling.

The intake-bypass runner lets the user exercise the *post-intake* pipeline
without re-running the GPT intake conversation, via "baseline + overrides":

  - A baseline snapshot is the structured intake output (operating_model_json,
    target_market_json, people_json, financials_json, financials_year1_json,
    marketing_model_json, fulfillment_json) captured once from a real,
    intake-complete draft. Post-intake consumes these structured JSON payloads,
    so reusing a real baseline guarantees the JSON is shaped exactly as
    post-intake expects.

  - Overrides are an EXHAUSTIVE, pre-filled spreadsheet. Every leaf of the
    baseline is a row addressed by a dotted path; the cell is pre-filled with
    the baseline value. The user edits any cell they want to change. A row takes
    effect only when its cell differs from the baseline value at that path, so
    an unedited sheet reproduces the baseline exactly.

This module holds the pieces both ``capture_intake_baseline.py`` and
``run_intake_bypass.py`` need: env/DB access, JSON helpers, and the generic
dotted-path override engine.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
DEFAULT_BASELINES_DIR = THIS_DIR / "intake_bypass_baselines"
DEFAULT_SCENARIOS_XLSX = THIS_DIR / "intake_bypass_scenarios.xlsx"

# Columns copied from the baseline draft into a fresh draft. Mirrors the proven
# clone in run_persisted_system_run.py:_clone_source_into_target_draft.
# Each entry is (sql_column, snapshot_key).
BASELINE_FLAT_COLUMNS: List[Tuple[str, str]] = [
  ("business_name", "business_name"),
  ("business_address", "business_address"),
  ("address_street", "address_street"),
  ("address_city", "address_city"),
  ("address_state", "address_state"),
  ("address_zip", "address_zip"),
  ("address_country", "address_country"),
  ("business_start_date", "business_start_date"),
]

BASELINE_JSON_COLUMNS: List[str] = [
  "messages_json",
  "operating_model_json",
  "target_market_json",
  "people_json",
  "financials_json",
  "marketing_model_json",
  "financials_year1_json",
  "realism_memo_json",
  "pending_ops_milestone_json",
  "fulfillment_json",
]

# The structured payloads post-intake consumes and the user may override.
# (messages_json/realism_memo_json/pending_ops_milestone_json are conversation /
# gate artifacts, not intake business inputs, so they are not exposed.)
STRUCTURED_PAYLOADS: List[str] = [
  "operating_model_json",
  "target_market_json",
  "people_json",
  "financials_json",
  "financials_year1_json",
  "marketing_model_json",
  "fulfillment_json",
]

RESERVED_FIELDS = {"baseline", "scenario_notes", "scenario_name"}
NULL_TOKEN = "(null)"

_MISSING = object()
_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


# ---------------------------------------------------------------------------
# Environment / DB
# ---------------------------------------------------------------------------
def load_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  env_path = ROOT / ".env"
  try:
    if env_path.exists():
      load_dotenv(env_path, override=False)
    else:
      load_dotenv(override=False)
  except Exception:
    pass


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def mysql_connect():
  import mysql.connector  # type: ignore

  host = _string(os.getenv("MYSQL_HOST"))
  user = _string(os.getenv("MYSQL_USER"))
  password = str(os.getenv("MYSQL_PASSWORD") or "")
  database = _string(os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME"))
  port_raw = _string(os.getenv("MYSQL_PORT") or "3306")
  if not (host and user and database):
    raise RuntimeError("MYSQL_HOST, MYSQL_USER, and MYSQL_DB must be configured in .env.")
  try:
    port = int(port_raw or "3306")
  except Exception:
    port = 3306
  return mysql.connector.connect(host=host, user=user, password=password, database=database, port=port)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def parse_json(value: Any) -> Any:
  if value is None:
    return None
  if isinstance(value, (dict, list)):
    return value
  if isinstance(value, (bytes, bytearray)):
    value = value.decode("utf-8", "replace")
  text = str(value).strip()
  if not text:
    return None
  try:
    return json.loads(text)
  except Exception:
    return value


def sql_json_value(value: Any) -> Any:
  if isinstance(value, (dict, list)):
    return json.dumps(value, ensure_ascii=False)
  return value


# ---------------------------------------------------------------------------
# Dotted-path engine
# ---------------------------------------------------------------------------
def parse_path(path: str) -> List[Any]:
  """'a.b[0].c' -> ['a', 'b', 0, 'c']."""
  tokens: List[Any] = []
  for m in _PATH_TOKEN_RE.finditer(path):
    key, idx = m.group(1), m.group(2)
    if idx is not None:
      tokens.append(int(idx))
    elif key is not None:
      tokens.append(key)
  return tokens


def get_by_path(obj: Any, tokens: List[Any]) -> Any:
  cur = obj
  for tok in tokens:
    if isinstance(tok, int):
      if isinstance(cur, list) and 0 <= tok < len(cur):
        cur = cur[tok]
      else:
        return _MISSING
    else:
      if isinstance(cur, dict) and tok in cur:
        cur = cur[tok]
      else:
        return _MISSING
  return cur


def set_by_path(obj: Any, tokens: List[Any], value: Any) -> None:
  cur = obj
  for i, tok in enumerate(tokens[:-1]):
    nxt = tokens[i + 1]
    if isinstance(tok, int):
      if not isinstance(cur, list):
        raise ValueError(f"path index [{tok}] applied to non-list at token {i}")
      while len(cur) <= tok:
        cur.append([] if isinstance(nxt, int) else {})
      cur = cur[tok]
    else:
      if not isinstance(cur, dict):
        raise ValueError(f"path key {tok!r} applied to non-dict at token {i}")
      if tok not in cur or cur[tok] is None:
        cur[tok] = [] if isinstance(nxt, int) else {}
      cur = cur[tok]
  last = tokens[-1]
  if isinstance(last, int):
    if not isinstance(cur, list):
      raise ValueError(f"path index [{last}] applied to non-list")
    while len(cur) <= last:
      cur.append(None)
    cur[last] = value
  else:
    cur[last] = value


def flatten_obj(prefix: str, obj: Any, out: List[Tuple[str, Any]]) -> None:
  """Append (dotted_path, leaf_value) for every leaf of obj."""
  if isinstance(obj, dict):
    for k, v in obj.items():
      flatten_obj(f"{prefix}.{k}", v, out)
  elif isinstance(obj, list):
    for i, v in enumerate(obj):
      flatten_obj(f"{prefix}[{i}]", v, out)
  else:
    out.append((prefix, obj))


def _to_number(raw: Any) -> float:
  if isinstance(raw, bool):
    raise ValueError(f"expected number, got bool {raw!r}")
  if isinstance(raw, (int, float)):
    return float(raw)
  text = str(raw).strip()
  had_percent = text.endswith("%")
  cleaned = text.replace("$", "").replace(",", "").replace("%", "").strip()
  val = float(cleaned)
  return val / 100.0 if had_percent else val


def coerce_to_type(raw: Any, baseline_value: Any) -> Any:
  """Coerce a spreadsheet cell to the baseline value's type where possible."""
  if isinstance(raw, str) and raw.strip() == NULL_TOKEN:
    return None
  if isinstance(baseline_value, bool):
    if isinstance(raw, bool):
      return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "y")
  if isinstance(baseline_value, int) and not isinstance(baseline_value, bool):
    return int(round(_to_number(raw)))
  if isinstance(baseline_value, float):
    return _to_number(raw)
  if baseline_value is None or baseline_value is _MISSING:
    # Unknown target type: try number, else string.
    try:
      return _to_number(raw)
    except Exception:
      return str(raw)
  return str(raw)


def values_equal(a: Any, b: Any) -> bool:
  if isinstance(a, bool) or isinstance(b, bool):
    return bool(a) == bool(b)
  if isinstance(a, (int, float)) and isinstance(b, (int, float)):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
  return a == b


def apply_overrides(
  *,
  flat: Dict[str, Any],
  structured: Dict[str, Any],
  overrides: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """Apply dotted-path overrides onto ``flat`` and ``structured`` in place.

  ``draft.<col>`` targets a flat draft column; ``<payload>.<path>`` targets a
  leaf in a structured JSON column. A row is applied only when its (coerced)
  cell value differs from the baseline value at that path. Blank cells inherit
  the baseline. The literal "(null)" sets null. Returns an audit list.
  """
  audit: List[Dict[str, Any]] = []
  for key, raw in overrides.items():
    field = _string(key)
    if not field or field.startswith("#") or field in RESERVED_FIELDS:
      continue
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
      continue  # inherit baseline

    if field.startswith("draft."):
      col = field[len("draft."):]
      new_val = None if (isinstance(raw, str) and raw.strip() == NULL_TOKEN) else _string(raw)
      old_val = flat.get(col)
      if values_equal(new_val, old_val):
        continue
      flat[col] = new_val
      audit.append({"field": field, "old": old_val, "new": new_val})
      continue

    head = re.split(r"[.\[]", field, 1)[0]
    if head not in STRUCTURED_PAYLOADS:
      raise ValueError(
        f"Unknown override target {field!r}. Address either 'draft.<col>' or "
        f"'<payload>.<path>' where <payload> in {STRUCTURED_PAYLOADS}."
      )
    tokens = parse_path(field)
    baseline_value = get_by_path(structured, tokens)
    coerced = coerce_to_type(raw, baseline_value)
    if baseline_value is not _MISSING and values_equal(coerced, baseline_value):
      continue  # unedited pre-filled cell
    set_by_path(structured, tokens, coerced)
    audit.append({
      "field": field,
      "old": (None if baseline_value is _MISSING else baseline_value),
      "new": coerced,
    })
  return audit


def load_baseline(baselines_dir: Path, name: str) -> Dict[str, Any]:
  name = _string(name)
  if not name:
    raise RuntimeError("Scenario is missing a 'baseline' value.")
  if name.endswith(".json"):
    name = name[: -len(".json")]
  path = baselines_dir / f"{name}.json"
  if not path.exists():
    available = sorted(p.stem for p in baselines_dir.glob("*.json")) if baselines_dir.exists() else []
    raise RuntimeError(f"Baseline {name!r} not found at {path}. Available: {available}")
  with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
  if not isinstance(data, dict) or "structured" not in data:
    raise RuntimeError(f"Baseline file {path} is malformed (missing 'structured').")
  return data
