import argparse
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple


def _load_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return

  root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  load_dotenv(os.path.join(root, ".env"))


def _json_load_maybe(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return None


def _get_path(obj: Any, path: str) -> Any:
  """
  Minimal dot-path helper supporting:
    - foo.bar
    - foo[0].bar
    - foo["key"].bar (not needed here)
  """
  cur = obj
  for part in [p for p in str(path or "").split(".") if p]:
    if cur is None:
      return None
    key = part
    idx: Optional[int] = None
    if "[" in part and part.endswith("]"):
      key = part[: part.index("[")]
      raw_idx = part[part.index("[") + 1 : -1].strip()
      try:
        idx = int(raw_idx)
      except Exception:
        idx = None
    if key:
      if not isinstance(cur, dict):
        return None
      cur = cur.get(key)
    if idx is not None:
      if not isinstance(cur, list) or idx < 0 or idx >= len(cur):
        return None
      cur = cur[idx]
  return cur


def _find_company_total_lob(card: Any) -> Optional[Dict[str, Any]]:
  if not isinstance(card, dict):
    return None
  lobs = card.get("lobs")
  if not isinstance(lobs, list):
    # Back-compat old shape: treat root as company_total.
    return {"drivers": card.get("drivers") or {}, "derived": card.get("derived") or {}}
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    if str(lob.get("lob_key") or "").strip() == "company_total":
      return lob
  return None


def _assert_equal(name: str, actual: Any, expected: Any) -> Tuple[bool, str]:
  if isinstance(expected, (list, tuple, set, frozenset)):
    ok = actual in expected
  else:
    ok = actual == expected
  return ok, f"{name}: expected={expected!r} actual={actual!r}"


@dataclass(frozen=True)
class Step:
  name: str
  message: str
  db_checks: Tuple[Tuple[str, str, Any], ...]
  card_checks: Tuple[Tuple[str, str, Any], ...]


def main() -> int:
  parser = argparse.ArgumentParser(description="Verify per-turn chat persistence into model JSON + card projection.")
  parser.add_argument("--draft-id", default="", help="Optional existing draft_id to reuse.")
  parser.add_argument("--start", action="store_true", help="Start the consult with an empty message first.")
  args = parser.parse_args()

  _load_env()

  # Import app after env load.
  repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  sys.path.insert(0, os.path.join(repo_root, "python"))
  from api import create_app  # type: ignore

  try:
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  except Exception:
    from intake_submission import get_mysql_connection  # type: ignore

  app = create_app()
  client = app.test_client()

  draft_id = str(args.draft_id or "").strip()
  client_id = ""

  if not draft_id:
    res = client.post("/api/intake-consult/session", json={})
    body = res.get_json(silent=True) or {}
    if res.status_code < 200 or res.status_code >= 300:
      print(f"FAIL: session create: HTTP {res.status_code} {body}")
      return 2
    draft_id = str(body.get("draft_id") or "").strip()
    client_id = str(body.get("client_id") or "").strip()
    if not draft_id:
      print("FAIL: session create did not return draft_id")
      return 2

  # Keep business details set so the app mirrors real usage.
  payload_base: Dict[str, Any] = {
    "draft_id": draft_id,
    "client_id": client_id or None,
    "business_name": "TestCo",
    "address": "123 Test St, Testville, FL 32000, USA",
    "business_start_date": "2026-03-01",
    "address_street": "123 Test St",
    "address_city": "Testville",
    "address_state": "FL",
    "address_zip": "32000",
    "address_country": "USA",
  }

  if args.start:
    res = client.post("/api/intake-consult", json={**payload_base, "message": ""})
    if res.status_code < 200 or res.status_code >= 300:
      print(f"FAIL: start consult: HTTP {res.status_code} {res.get_json(silent=True)}")
      return 2

  steps = (
    Step(
      name="Operating model: units_per_week_capacity",
      message="We can complete 100 units per week.",
      db_checks=(("operating_model_json", "$.units_per_week_capacity", 100),),
      card_checks=(("operating_model", "units_per_week_capacity", 100),),
    ),
    Step(
      name="Pricing model: unit_price",
      message="Unit price is 1000.",
      db_checks=(("pricing_model_json", "$.unit_price", 1000),),
      card_checks=(("pricing", "drivers.unit_price.value", 1000),),
    ),
    Step(
      name="Ops: starting_revenue (used for revenue model rollup)",
      message="Year-1 revenue will be 1040000.",
      db_checks=(("operating_model_json", "$.starting_revenue", 1040000),),
      card_checks=(),
    ),
    Step(
      name="Financials: cash_on_hand",
      message="We have $50000 cash on hand.",
      db_checks=(("financials_json", "$.cash_on_hand", 50000),),
      card_checks=(("financials", "cash_on_hand", 50000),),
    ),
    # The remaining models depend on chat-driven driver capture; they may fail until implemented.
    Step(
      name="Marketing model: monthly_marketing_budget",
      message="Our monthly marketing budget is 2000.",
      db_checks=(("marketing_model_json", "$.lobs[0].drivers.monthly_marketing_budget.value", 2000),),
      card_checks=(("marketing", "drivers.monthly_marketing_budget.value", 2000),),
    ),
    Step(
      name="Revenue model: operating_weeks_per_year",
      message="We operate 52 weeks per year.",
      db_checks=(("revenue_model_json", "$.lobs[0].drivers.operating_weeks_per_year.value", 52),),
      card_checks=(("revenue", "drivers.operating_weeks_per_year.value", 52),),
    ),
    Step(
      name="COGS model: cost_per_unit + derived year1_cogs",
      message="COGS is $10 per unit.",
      db_checks=(
        ("cogs_model_json", "$.lobs[0].drivers.cost_per_unit.value", 10),
        ("cogs_model_json", "$.lobs[0].derived.year1_cogs.value", 10400),
        ("year1_cogs", "", 10400),
      ),
      card_checks=(
        ("cogs", "drivers.cost_per_unit.value", 10),
        ("cogs", "derived.year1_cogs.value", 10400),
      ),
    ),
    Step(
      name="COGS recompute: change price -> year1_cogs updates",
      message="Actually, unit price is 2000.",
      db_checks=(
        ("pricing_model_json", "$.unit_price", 2000),
        ("cogs_model_json", "$.lobs[0].derived.year1_cogs.value", 5200),
        ("year1_cogs", "", 5200),
      ),
      card_checks=(
        ("pricing", "drivers.unit_price.value", 2000),
        ("cogs", "derived.year1_cogs.value", 5200),
      ),
    ),
    Step(
      name="G&A model: rent + insurance -> derived year1_gna_total",
      message="Monthly rent is 1000 and monthly insurance is 200.",
      db_checks=(
        ("gna_model_json", "$.lobs[0].drivers.monthly_rent_expense.value", 1000),
        ("gna_model_json", "$.lobs[0].drivers.monthly_insurance_expense.value", 200),
        ("gna_model_json", "$.lobs[0].derived.year1_gna_total.value", 14400),
        ("year1_gna_total", "", 14400),
      ),
      card_checks=(
        ("gna", "drivers.monthly_rent_expense.value", 1000),
        ("gna", "drivers.monthly_insurance_expense.value", 200),
        ("gna", "derived.year1_gna_total.value", 14400),
      ),
    ),
    Step(
      name="Fulfillment model: lead_time",
      message="Typical lead time is 2 days. Fulfillment is in-house.",
      db_checks=(("fulfillment_model_json", "$.lobs[0].drivers.lead_time.value", "2 days"),),
      card_checks=(("fulfillment", "drivers.lead_time.value", "2 days"),),
    ),
    Step(
      name="Ops concept model: primary_constraint",
      message="Primary constraint is my time. Operating unit is one completed plan. Process: intake -> generate -> revise -> deliver.",
      db_checks=(("ops_concept_model_json", "$.lobs[0].drivers.primary_constraint.value", ("my time", "owner time", "founder time")),),
      card_checks=(("ops_concept", "drivers.primary_constraint.value", ("my time", "owner time", "founder time")),),
    ),
    Step(
      name="Milestones model: milestones",
      message="Milestone: Launch MVP by March 2026.",
      db_checks=(("milestones_model_json", "$.lobs[0].drivers.milestones.value[0].title", "Launch MVP"),),
      card_checks=(("milestones", "drivers.milestones.value[0].title", "Launch MVP"),),
    ),
    Step(
      name="Headcount model: roles",
      message="Headcount: 3 staff at $20/hour, 40 hours/week, 52 weeks/year.",
      db_checks=(("headcount_model_json", "$.lobs[0].drivers.roles.value[0].employee_count", 3),),
      card_checks=(("headcount", "drivers.roles.value[0].employee_count", 3),),
    ),
  )

  # Helper to query the draft row each time.
  def fetch_draft_row() -> Dict[str, Any]:
    conn = get_mysql_connection()
    try:
      cur = conn.cursor(dictionary=True)
      try:
        cur.execute(
          """
          SELECT draft_id,
                 operating_model_json,
                 target_market_json,
                 people_json,
                 financials_json,
                 marketing_model_json,
                 pricing_model_json,
                 revenue_model_json,
                 headcount_model_json,
                 fulfillment_model_json,
                 ops_concept_model_json,
                 milestones_model_json,
                 cogs_model_json,
                 gna_model_json,
                 year1_cogs,
                 year1_gna_total
          FROM intake_consult_drafts
          WHERE draft_id = %s
          """,
          (draft_id,),
        )
        row = cur.fetchone() or {}
      finally:
        cur.close()
    finally:
      conn.close()
    return dict(row)

  def json_extract_from_row(row: Dict[str, Any], col: str, json_path: str) -> Any:
    if not json_path and str(col or "") in ("year1_cogs", "year1_gna_total"):
      val = row.get(col)
      if isinstance(val, Decimal):
        try:
          return float(val)
        except Exception:
          return str(val)
      return val
    doc = _json_load_maybe(row.get(col))
    if doc is None:
      return None
    # Support minimal "$." prefix
    p = str(json_path or "").strip()
    if p.startswith("$."):
      p = p[2:]
    return _get_path(doc, p)

  def card_extract(shared_ctx: Dict[str, Any], model: str, dot_path: str) -> Any:
    model_cards = shared_ctx.get("model_cards") if isinstance(shared_ctx, dict) else None
    if not isinstance(model_cards, dict):
      return None
    if model in ("operating_model", "target_market", "people_capability", "financials"):
      base = shared_ctx.get(model)
      return _get_path(base, dot_path)
    card = model_cards.get(model)
    lob = _find_company_total_lob(card)
    if lob is None:
      return None
    return _get_path(lob, dot_path)

  all_ok = True
  for step in steps:
    step_ok = True
    res = client.post("/api/intake-consult", json={**payload_base, "message": step.message})
    if res.status_code < 200 or res.status_code >= 300:
      step_ok = False
      all_ok = False
      print(f"FAIL: {step.name}: consult HTTP {res.status_code} {res.get_json(silent=True)}")
      continue

    row = fetch_draft_row()
    for col, jpath, expected in step.db_checks:
      actual = json_extract_from_row(row, col, jpath)
      ok, msg = _assert_equal(f"{step.name} DB {col}{jpath}", actual, expected)
      if not ok:
        step_ok = False
        all_ok = False
        print(f"FAIL: {msg}")

    shared_res = client.get("/api/shared-context", query_string={"draft_id": draft_id})
    shared_body = shared_res.get_json(silent=True) or {}
    shared_ctx = shared_body.get("shared_context") if isinstance(shared_body, dict) else None
    if not isinstance(shared_ctx, dict):
      step_ok = False
      all_ok = False
      print(f"FAIL: {step.name}: shared_context invalid: HTTP {shared_res.status_code}")
      continue

    for model, dot_path, expected in step.card_checks:
      actual = card_extract(shared_ctx, model, dot_path)
      ok, msg = _assert_equal(f"{step.name} CARD {model}.{dot_path}", actual, expected)
      if not ok:
        step_ok = False
        all_ok = False
        print(f"FAIL: {msg}")

    if step_ok:
      print(f"OK: {step.name}")

  print(f"Done. draft_id={draft_id}")
  return 0 if all_ok else 1


if __name__ == "__main__":
  raise SystemExit(main())
