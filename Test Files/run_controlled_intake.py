import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPTED_RUNNER_PATH = THIS_DIR / "run_scripted_intake.py"


def _load_scripted_runner():
  spec = importlib.util.spec_from_file_location("run_scripted_intake_shared", str(SCRIPTED_RUNNER_PATH))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load scripted runner from {SCRIPTED_RUNNER_PATH}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


_SCRIPTED = _load_scripted_runner()


SCENARIO: Dict[str, Any] = {
  "bootstrap": {
    "business_name": "Example Controlled Business",
    "business_start_date": "08/05/2024",
    "address": "123 Example Street, Austin, TX 78701",
    "address_street": "123 Example Street",
    "address_city": "Austin",
    "address_state": "TX",
    "address_zip": "78701",
    "address_country": "USA",
  },
  "ops": {
    "business_description": "Replace this with the exact business description you want the user to say.",
    "customer_type": "Replace this with the exact customer-type answer.",
    "products_confirmed": "Yes, track those as separate products.",
    "legal_entity": "LLC.",
    "delivery_method": "Yes, that delivery model is accurate.",
    "fulfillment_confirmation": "Yes, that's accurate.",
    "sales_channel": "Most customers find and book us online, with some phone inquiries as well.",
    "geography": "Austin and nearby communities in Travis County.",
    "growth_lever": "Adding provider capacity over time is the main growth lever.",
    "competitive_advantage": "Replace with the exact competitive-advantage answer you want.",
    "goal_12_months": "Replace with the exact 12-month goal answer you want.",
    "confirmation": "Yes, that's correct.",
    "products": [
      {
        "product_name": "Product 1",
        "aliases": [],
        "unit_definition": "Replace with exact unit definition.",
        "capacity": "Replace with exact capacity answer.",
        "utilization": "Replace with exact utilization answer.",
        "price": "Replace with exact price answer.",
      }
    ],
  },
  "market": {
    "gender": "Keep it open to all genders.",
    "age_range": "Replace with exact age-range answer.",
    "income_range": "Replace with exact income-range answer.",
    "education": "Replace with exact education answer.",
    "profile_detail_choice": "Replace with exact target-profile detail answer.",
    "employment_mix": "Replace with exact employment answer.",
    "confirmation": "Yes, that looks right.",
  },
  "people": {
    "owner_background": "Replace with exact owner background answer.",
    "other_key_people": "I'm currently the only key person involved in the business.",
    "confirmation": "Yes, that looks right.",
  },
  "financials": {
    "revenue_setup": "Replace with exact Year-1 revenue answer.",
    "cogs": "Replace with exact COGS answer.",
    "payroll": "Replace with exact payroll answer.",
    "payroll_detail": "Replace with exact payroll-detail answer if needed.",
    "monthly_rent_expense": "Replace with exact monthly rent answer.",
    "other_operating_expense": "Replace with exact other operating expense answer.",
    "other_monthly_debt_payments": "Replace with exact other monthly debt answer.",
    "cash_on_hand": "Replace with exact cash-on-hand answer.",
    "ar_balance": "Replace with exact AR balance answer.",
    "ap_balance": "Replace with exact AP balance answer.",
    "inventory_balance": "Replace with exact inventory balance answer.",
    "current_capex": "Replace with exact current capex answer.",
    "initial_assets": "Replace with exact initial assets answer.",
    "initial_lease": "Replace with exact initial lease answer like 1200,monthly or 0,none.",
    "initial_equity": "Replace with exact initial equity answer.",
    "total_debt_outstanding": "Replace with exact total debt answer.",
    "annual_interest_payment": "Replace with exact annual interest answer.",
    "annual_principal_payment": "Replace with exact annual principal answer.",
    "owner_compensation": "Replace with exact owner compensation answer.",
    "confirmation": "Yes, that's right.",
  },
  "fallback": {
    "ops": [],
    "market": [],
    "people": [],
    "financials": [],
  },
  "overrides": [],
}


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Run a controlled intake simulation by editing the SCENARIO block in this file."
  )
  parser.add_argument("--base-url", default="", help="Optional override for app base URL.")
  parser.add_argument("--max-turns", type=int, default=80)
  parser.add_argument("--output-dir", default="")
  parser.add_argument("--persisted-output-dir", default="")
  parser.add_argument(
    "--print-template",
    action="store_true",
    help="Print the current SCENARIO template and exit.",
  )
  args = parser.parse_args()

  if args.print_template:
    print(_SCRIPTED.json.dumps(SCENARIO, indent=2, ensure_ascii=False))
    return 0

  _SCRIPTED._SHARED._load_env()
  base_url = str(args.base_url or "").strip() or _SCRIPTED.os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050")
  output_dir = str(args.output_dir or "").strip() or _SCRIPTED._SHARED.DEFAULT_TEST_RUNS_DIR
  persisted_output_dir = str(args.persisted_output_dir or "").strip() or _SCRIPTED._SHARED.DEFAULT_TEST_RUNS_DATA_DIR
  return _SCRIPTED._run_spec(
    spec_path="<inline_scenario>",
    spec=SCENARIO,
    base_url=base_url.rstrip("/"),
    max_turns=int(args.max_turns),
    output_dir=output_dir,
    persisted_output_dir=persisted_output_dir,
  )


if __name__ == "__main__":
  raise SystemExit(main())
