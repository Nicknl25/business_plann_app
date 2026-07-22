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
    # A non-numeric string (e.g. the "amount,period" lease format like "0,none")
    # cannot be an int -- keep it as a string so mirror_and_shape/validate handle
    # it, instead of crashing the whole harness in _to_number.
    try:
      return int(round(_to_number(raw)))
    except (TypeError, ValueError):
      return str(raw)
  if isinstance(baseline_value, float):
    try:
      return _to_number(raw)
    except (TypeError, ValueError):
      return str(raw)
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
    # The sheet is the spec: every non-blank row applies, and every applied row
    # is recorded in the audit -- even when the typed value equals the baseline.
    # End state per path is exactly what the user wrote; blank cells inherit.
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


# ---------------------------------------------------------------------------
# Harness-side coherence shaping + validation.
#
# DESIGN CONSTRAINT: the harness is a PRODUCER of valid SQL draft rows. Every
# bit of coherence cleanup and validation happens HERE, before the SQL write,
# so the app pipeline reads SQL exactly as it does for real intake. The app is
# NEVER modified to tolerate hand-authored input. Delete Test Files/ and the app
# is unchanged.
# ---------------------------------------------------------------------------


# initial_lease is a RECURRING lease payment beyond main rent. Real intake stores
# it as an "amount,period" string (financials_consultant intake prompt: "store as
# 'amount,period'... If none, record '0,none'"). The app's finmo bridge annualizes
# it into a capital-lease ROU asset; a BARE number silently defaults to MONTHLY
# (x12), so a total/one-time value dropped into this monthly field becomes a 12x-
# inflated ROU asset (the $290k -> $3.48M dental bug). The template/baselines store
# a bare 0, and an invented business can fill a bare number -- so normalize the unit
# HERE (harness), matching real intake, and flag implausible values before SQL.
_LEASE_PERIOD_MULTIPLIER = {
  "daily": 365.0, "weekly": 52.0, "monthly": 12.0, "quarterly": 4.0,
  "yearly": 1.0, "annual": 1.0, "one-time": 1.0, "unknown": 1.0, "none": 0.0,
}


def _annualized_initial_lease(value: Any) -> Optional[float]:
  """Annual lease commitment implied by an initial_lease value, mirroring the
  app's _annualized_lease_commitment (bare number => monthly x12)."""
  if value is None or value == "":
    return None
  if isinstance(value, (int, float)) and not isinstance(value, bool):
    return max(0.0, float(value)) * 12.0
  raw = str(value).strip().lower()
  if not raw or raw in {"0", "0,none", "none", "no", "n/a", "na", "zero"}:
    return 0.0
  amount_part, _, period_part = raw.partition(",")
  try:
    amount = max(0.0, _to_number(amount_part))
  except (TypeError, ValueError):
    return None
  period_part = period_part.strip()
  if not period_part:
    return amount * 12.0  # app default for a bare amount
  return amount * _LEASE_PERIOD_MULTIPLIER.get(period_part, 1.0)


def _canonicalize_initial_lease(value: Any) -> Any:
  """Return initial_lease in real-intake's explicit "amount,period" form so the
  app can never silently read a bare number as monthly. 0/empty -> "0,none";
  a bare amount -> "<amount>,monthly" (the app's own default, made visible);
  an already-"amount,period" string is passed through normalized. Non-numeric
  junk is left untouched for validate_scenario to flag."""
  if value is None or value == "":
    return "0,none"
  if isinstance(value, str) and "," in value:
    amount_part, _, period_part = value.strip().partition(",")
    period_part = period_part.strip().lower() or "monthly"
    try:
      amt = max(0.0, _to_number(amount_part))
    except (TypeError, ValueError):
      return value
    if amt == 0.0 or period_part == "none":
      return "0,none"
    return f"{int(amt) if float(amt).is_integer() else amt},{period_part}"
  try:
    amt = max(0.0, _to_number(value))
  except (TypeError, ValueError):
    return value
  if amt == 0.0:
    return "0,none"
  return f"{int(amt) if float(amt).is_integer() else amt},monthly"


def mirror_and_shape_scenario(flat: Dict[str, Any], structured: Dict[str, Any]) -> None:
  """Apply the two coherence gotchas IN PLACE before the SQL write so the
  app pipeline never sees an incoherent hand-authored draft:

    1. NAICS mirror -- people_json.business_naics_6 is the PRIMARY NAICS source
       post-intake reads (before operating_model). Force it to equal the
       operating-model NAICS so the two can never disagree.
    2. financials_year1 derive -- post-intake recomputes year1 revenue from the
       operating_model LOBs, and discards an injected year1 that disagrees. Omit
       it ({}) so it is always cleanly derived from ops.
  """
  om = structured.get("operating_model_json")
  ppl = structured.get("people_json")
  naics = om.get("business_naics_6") if isinstance(om, dict) else None
  if isinstance(ppl, dict) and naics:
    ppl["business_naics_6"] = naics
  structured["financials_year1_json"] = {}

  # initial_lease unit coherence -- make the monthly-vs-total unit explicit so a
  # bare number can never be silently annualized as $X/month by the app.
  fin = structured.get("financials_json")
  if isinstance(fin, dict) and "initial_lease" in fin:
    fin["initial_lease"] = _canonicalize_initial_lease(fin.get("initial_lease"))

  # other-opex basis coherence -- the app's field contract captures
  # other_operating_expense MONTHLY and derives other_opex_absolute
  # (annual = monthly x 12) at intake. The scenario sheets were authored
  # with ANNUAL values in this field; without the derivation, every
  # runtime consumer's monthly-x12 fallback fires on already-annual
  # numbers and G&A lands ~12x too high (Meridian 3.8% -> 44.7% of
  # revenue). Honor the sheets' annual authorship AND the app's field
  # contract: absolute = the sheet value (annual), monthly = value / 12
  # -- the draft then looks exactly like a real-intake draft.
  if isinstance(fin, dict) and fin.get("other_opex_absolute") in (None, ""):
    try:
      _ooe_annual = float(fin.get("other_operating_expense"))
    except (TypeError, ValueError):
      _ooe_annual = None
    if _ooe_annual is not None and _ooe_annual >= 0:
      fin["other_opex_absolute"] = round(_ooe_annual, 2)
      fin["other_operating_expense"] = round(_ooe_annual / 12.0, 2)

  # Type coherence for NEW array elements (added LOBs / people have no baseline
  # leaf to anchor the cell type, so a numeric-looking string can land as a
  # float). The app contract types these exactly; we shape the harness output to
  # match it -- never the reverse.
  if isinstance(om, dict):
    for lob in om.get("lob_models") or []:
      if not isinstance(lob, dict):
        continue
      for prod in lob.get("products") or []:
        if not isinstance(prod, dict):
          continue
        pname = prod.get("product_name")
        # unit_name / unit_description default to the product name when a newly
        # added product omits them (both are required strings).
        if pname and not prod.get("unit_name"):
          prod["unit_name"] = pname
        if pname and not prod.get("unit_description"):
          prod["unit_description"] = pname
  if isinstance(ppl, dict):
    for person in ppl.get("people") or []:
      if isinstance(person, dict) and person.get("experience_years") is not None:
        # experience_years is a STRING in the contract (e.g. "7"), not a number.
        ey = person["experience_years"]
        if isinstance(ey, float) and ey.is_integer():
          ey = int(ey)
        person["experience_years"] = str(ey)


_CONFIDENCE_PATHS = (
  ("operating_model_json", "confidence"),
  ("people_json", "confidence"),
  ("target_market_json", "confidence"),
)


def validate_scenario(flat: Dict[str, Any], structured: Dict[str, Any]) -> List[str]:
  """Return human-readable problems that would make this draft invalid at the
  INTAKE->POST_INTAKE contract or trip a coherence gotcha. Empty list == OK.

  Run in the harness BEFORE the SQL write so a missing required field, a string
  confidence, or an unfilled template placeholder surfaces with a clear message
  up front -- instead of a 500 mid-pipeline. This imports the app's contract for
  validation only; it never modifies it."""
  problems: List[str] = []

  # 1. Confidence-as-float (clearer than the raw pydantic message).
  for payload_key, field in _CONFIDENCE_PATHS:
    val = (structured.get(payload_key) or {}).get(field)
    if val is not None and not isinstance(val, (int, float)):
      problems.append(
        f"{payload_key}.{field} must be a NUMBER 0-1 (e.g. 0.7), got {val!r} -- not 'high'/'medium'."
      )

  # 2. The INTAKE->POST_INTAKE contract (the real gatekeeper).
  try:
    import sys as _sys
    _py = str(ROOT / "python")
    if _py not in _sys.path:
      _sys.path.insert(0, _py)
    from client_intake_and_finmo.post_intake_contracts.intake_draft_contract import (  # type: ignore
      IntakeDraftContract,
    )
    import pydantic  # type: ignore
    payload = {k: structured.get(k) for k in STRUCTURED_PAYLOADS}
    try:
      IntakeDraftContract.model_validate(payload)
    except pydantic.ValidationError as exc:
      for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        # planning_context_summary_json is written by the runner, not the sheet.
        if "planning_context_summary_json" in loc:
          continue
        problems.append(f"{loc}: {err.get('msg')} (got {err.get('input')!r})")
  except Exception as exc:  # contract import/parse issue -- never crash the harness
    problems.append(f"contract check could not run: {type(exc).__name__}: {exc}")

  # 3. Unfilled template placeholders ("<...>" sentinels / 000000 NAICS).
  placeholders: List[str] = []

  def _scan(prefix: str, obj: Any) -> None:
    if isinstance(obj, dict):
      for k, v in obj.items():
        _scan(f"{prefix}.{k}", v)
    elif isinstance(obj, list):
      for i, v in enumerate(obj):
        _scan(f"{prefix}[{i}]", v)
    elif isinstance(obj, str):
      s = obj.strip()
      if s.startswith("<") and s.endswith(">"):
        placeholders.append(prefix)

  for key in STRUCTURED_PAYLOADS:
    _scan(key, structured.get(key))
  naics = (structured.get("operating_model_json") or {}).get("business_naics_6")
  if naics in (None, "", "000000"):
    placeholders.append("operating_model_json.business_naics_6 (still the 000000 placeholder)")
  if placeholders:
    problems.append("Unfilled template placeholders: " + ", ".join(placeholders[:15]))

  # (A former check 4 blocked sub-floor wages here. Removed: the app now
  # GROUNDS sub-floor wages up to the data-derived OEWS floor and continues --
  # ground-don't-crash -- so blocking at the harness would diverge from real
  # production behavior instead of replicating it.)

  # 4. initial_lease sanity -- a recurring lease payment can't exceed revenue.
  # Catches a total/one-time value dropped into the monthly lease field (the
  # $290k -> $3.48M/yr ROU-asset bug) before it silently crushes net income.
  fin = structured.get("financials_json") or {}
  if isinstance(fin, dict):
    annualized_lease = _annualized_initial_lease(fin.get("initial_lease"))
    try:
      revenue = _to_number(fin.get("current_revenue")) if fin.get("current_revenue") not in (None, "") else None
    except (TypeError, ValueError):
      revenue = None
    # An EXPLICIT one-time capital lease is already disambiguated — the
    # 12x-inflation bug this check guards against is a bare/monthly value;
    # a one-time facility lease legitimately exceeds one year's revenue
    # (Big_Shipper $960M, Understory's $300k grow-facility vs $298k/yr).
    _lease_raw = str(fin.get("initial_lease") or "").strip().lower()
    _is_one_time = _lease_raw.partition(",")[2].strip() in ("one-time", "onetime", "one_time", "once")
    if annualized_lease and revenue and annualized_lease > revenue and not _is_one_time:
      problems.append(
        f"financials.initial_lease annualizes to ${annualized_lease:,.0f}, which EXCEEDS "
        f"current_revenue ${revenue:,.0f} -- this is a monthly lease-payment field, so a "
        f"total/one-time value here inflates the capital-lease ROU asset ~12x. Use "
        f"\"amount,period\" (e.g. \"4800,monthly\", \"58000,yearly\", or \"0,none\")."
      )

  return problems
