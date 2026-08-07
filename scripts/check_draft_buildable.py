"""Standalone pre-submit buildability checker (CW-013).

Validates a draft's model-input assembly against FinmoModelInputContract
WITHOUT a planning run - the same producer contract the submit path
enforces, runnable in one command before Cowork (or a client) ever
presses Submit:

  python scripts/check_draft_buildable.py <draft_id>

Exit 0 = buildable. Exit 1 = the contract rejected the assembly (the
exact submit-time failure, caught early). Exit 2 = usage/load error.

This exists because CW-013's G&A lever reached submit carrying
percent-points (1.868782) where the contract requires a fraction - a
full Cowork run was burned discovering what this one command now checks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "python" / "client_intake_and_finmo"))

try:
  from dotenv import load_dotenv

  load_dotenv(REPO / ".env")
except Exception:
  pass


def _load(value):
  if value is None:
    return {}
  if isinstance(value, (dict, list)):
    return value
  try:
    return json.loads(value)
  except Exception:
    return {}


def main() -> int:
  if len(sys.argv) < 2:
    print("usage: check_draft_buildable.py <draft_id>")
    return 2
  draft_id = sys.argv[1].strip()

  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  cur = conn.cursor(dictionary=True)
  cur.execute(
    "SELECT business_name, operating_model_json, people_json, financials_json, "
    "financials_year1_json, marketing_model_json, forecast_quarters_json "
    "FROM intake_consult_drafts WHERE draft_id LIKE %s",
    (draft_id + "%",),
  )
  row = cur.fetchone()
  conn.close()
  if not row:
    print(f"draft not found: {draft_id}")
    return 2

  from client_intake_and_finmo.finmo_bridge import build_python_model_input_json  # type: ignore
  from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore
    SIDE_PRODUCER,
    validate_model_input_at_boundary,
  )

  business_facts = {"business_name": row.get("business_name")}
  fin_json = _load(row.get("financials_json"))
  ops_json = _load(row.get("operating_model_json"))
  try:
    starting_ppe = float(fin_json.get("initial_assets") or 0.0)
  except (TypeError, ValueError):
    starting_ppe = 0.0
  # Ledger 1d: use the SAME Python-derived maintenance_rate production
  # uses (NAICS cascade w/ conservative default), never a hardcoded 0.05
  # - checker-vs-production drift is the CW-014 lesson shape.
  try:
    from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
      _derive_maintenance_capex_percent_from_naics,
    )
    maintenance_rate = float(
      _derive_maintenance_capex_percent_from_naics(
        business_facts=business_facts,
        ops_json=ops_json,
        financials_json=fin_json,
        financials_year1_json=_load(row.get("financials_year1_json")),
      ).get("maintenance_rate") or 0.05
    )
  except Exception:
    maintenance_rate = 0.05
  model_input = build_python_model_input_json(
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=_load(row.get("people_json")),
    financials_json=fin_json,
    financials_year1_json=_load(row.get("financials_year1_json")),
    marketing_model_json=_load(row.get("marketing_model_json")),
    forecast_starting_ppe=starting_ppe,
    maintenance_rate=maintenance_rate,
    controller_input_seed=[],
    forecast_quarters=[],
    business_name=str(row.get("business_name") or ""),
  )
  try:
    validate_model_input_at_boundary(model_input, side=SIDE_PRODUCER)
  except Exception as exc:
    print(f"NOT BUILDABLE: {type(exc).__name__}")
    print(str(exc)[:1500])
    # Show every ratio-semantics expense row so the offending value is
    # visible without a debugger.
    for i, exp_row in enumerate(
      ((model_input.get("sections") or {}).get("expenses") or [])
    ):
      if isinstance(exp_row, dict) and exp_row.get("input_semantics") == "percent_of_revenue":
        vals = exp_row.get("values") or []
        bad = [v for v in vals if isinstance(v, (int, float)) and not 0.0 <= v <= 1.0]
        marker = "  <-- OUT OF [0,1]" if bad else ""
        print(f"  expenses[{i}] {exp_row.get('label')}: {vals[:4]}{marker}")
    return 1
  print(f"BUILDABLE: {draft_id} ({row.get('business_name')}) - model-input contract passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
