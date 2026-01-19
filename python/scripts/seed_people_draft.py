from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any, Dict

from intake_submission import get_mysql_connection
from intake_consult_draft import create_draft, update_draft


def _today_iso() -> str:
  return date.today().isoformat()


def _build_operating_model(args: argparse.Namespace) -> Dict[str, Any]:
  return {
    "business_type": args.business_type,
    "consumer_type": args.consumer_type,
    "business_stage": args.business_stage,
    "unit_name": args.unit_name,
    "unit_description": args.unit_description,
    "units_per_week_capacity": args.units_per_week_capacity,
    "unit_price": args.unit_price,
    "shipping_method": args.shipping_method,
    "sales_modality": args.sales_modality,
    "geographic_scope": args.geographic_scope,
    "geographic_coverage": args.geographic_coverage,
    "countries": [args.country],
    "capacity_driver": args.capacity_driver,
    "primary_growth_lever": args.primary_growth_lever,
    "legal_entity": args.legal_entity,
    "business_description_summary": (
      f"Seeded ops summary for {{fact:business.name}}. "
      f"Core unit is {{fact:ops.unit_name}} at {{fact:ops.unit_price}} "
      f"with {{fact:ops.units_per_week_capacity}} per week."
    ),
  }


def _build_target_market(args: argparse.Namespace) -> Dict[str, Any]:
  return {
    "consumer_type": args.consumer_type,
    "target_market_summary": (
      "Seeded target market summary for {{fact:business.name}} "
      "serving {{fact:market.consumer_type}} customers."
    ),
    "confidence": 0.9,
  }


def main() -> None:
  parser = argparse.ArgumentParser(description="Seed a draft and jump intake to People.")
  parser.add_argument("--business-name", default="Seeded Test Co")
  parser.add_argument("--business-type", default="Business Consulting Firm")
  parser.add_argument("--consumer-type", default="b2b", choices=["consumer", "b2b", "mixed"])
  parser.add_argument("--business-stage", default="early-stage", choices=["pre-revenue", "early-stage", "operating"])
  parser.add_argument("--unit-name", default="project")
  parser.add_argument("--unit-description", default="One completed client project.")
  parser.add_argument("--units-per-week-capacity", type=float, default=10)
  parser.add_argument("--unit-price", type=float, default=1000)
  parser.add_argument("--shipping-method", default="digital delivery")
  parser.add_argument("--sales-modality", default="online", choices=["physical", "online", "hybrid"])
  parser.add_argument("--geographic-scope", default="national", choices=["local", "regional", "national", "international"])
  parser.add_argument("--geographic-coverage", default="United States")
  parser.add_argument("--country", default="United States")
  parser.add_argument("--capacity-driver", default="labor", choices=["labor", "system", "demand"])
  parser.add_argument("--primary-growth-lever", default="Increase demand")
  parser.add_argument("--legal-entity", default="LLC")
  parser.add_argument("--business-address", default="777 N Market St, Jacksonville, FL 32202, USA")
  parser.add_argument("--address-street", default="777 N Market St")
  parser.add_argument("--address-city", default="Jacksonville")
  parser.add_argument("--address-state", default="FL")
  parser.add_argument("--address-zip", default="32202")
  parser.add_argument("--address-country", default="USA")
  parser.add_argument("--business-start-date", default=_today_iso())
  args = parser.parse_args()

  conn = get_mysql_connection()
  try:
    draft = create_draft(conn)
    draft_id = str(draft.get("draft_id") or "").strip()
    operating_model = _build_operating_model(args)
    target_market = _build_target_market(args)

    updates = {
      "business_name": args.business_name,
      "business_address": args.business_address,
      "address_street": args.address_street,
      "address_city": args.address_city,
      "address_state": args.address_state,
      "address_zip": args.address_zip,
      "address_country": args.address_country,
      "business_start_date": args.business_start_date,
      "operating_model_json": json.dumps(operating_model, ensure_ascii=True),
      "target_market_json": json.dumps(target_market, ensure_ascii=True),
      "ops_confirmed": 1,
      "market_confirmed": 1,
      "people_confirmed": 0,
      "financials_confirmed": 0,
      "consistency_passed": 0,
      "active_focus": "people",
    }
    update_draft(conn, draft_id=draft_id, updates=updates)
  finally:
    conn.close()

  print("Seeded draft:")
  print(json.dumps({"draft_id": draft_id, "active_focus": "people"}, indent=2))


if __name__ == "__main__":
  main()
