import argparse
import importlib.util
import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List


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


TEMPLATE = textwrap.dedent(
  """
  BUSINESS_NAME: Example Controlled Business
  BUSINESS_START_DATE: 08/05/2024
  ADDRESS: 123 Example Street, Austin, TX 78701
  ADDRESS_STREET: 123 Example Street
  ADDRESS_CITY: Austin
  ADDRESS_STATE: TX
  ADDRESS_ZIP: 78701
  ADDRESS_COUNTRY: USA

  OPS_BUSINESS_DESCRIPTION: Replace with the exact business description you want the user to say.
  OPS_CUSTOMER_TYPE: Replace with the exact customer-type answer.
  OPS_PRODUCTS_CONFIRMED: Yes, track those as separate products.
  OPS_LEGAL_ENTITY: LLC.
  OPS_DELIVERY_METHOD: Yes, that delivery model is accurate.
  OPS_FULFILLMENT_CONFIRMATION: Yes, that's accurate.
  OPS_SALES_CHANNEL: Most customers find and book us online, with some phone inquiries as well.
  OPS_GEOGRAPHY: Austin and nearby communities in Travis County.
  OPS_GROWTH_LEVER: Adding provider capacity over time is the main growth lever.
  OPS_COMPETITIVE_ADVANTAGE: Replace with the exact competitive-advantage answer you want.
  OPS_GOAL_12_MONTHS: Replace with the exact 12-month goal answer you want.
  OPS_CONFIRMATION: Yes, that's correct.

  PRODUCT_1_NAME: Product 1
  PRODUCT_1_ALIASES:
  PRODUCT_1_UNIT_DEFINITION: Replace with exact unit definition.
  PRODUCT_1_CAPACITY: Replace with exact capacity answer.
  PRODUCT_1_UTILIZATION: Replace with exact utilization answer.
  PRODUCT_1_PRICE: Replace with exact price answer.

  PRODUCT_2_NAME:
  PRODUCT_2_ALIASES:
  PRODUCT_2_UNIT_DEFINITION:
  PRODUCT_2_CAPACITY:
  PRODUCT_2_UTILIZATION:
  PRODUCT_2_PRICE:

  MARKET_GENDER: Keep it open to all genders.
  MARKET_AGE_RANGE: Replace with exact age-range answer.
  MARKET_INCOME_RANGE: Replace with exact income-range answer.
  MARKET_EDUCATION: Replace with exact education answer.
  MARKET_PROFILE_DETAIL_CHOICE: Replace with exact target-profile detail answer.
  MARKET_EMPLOYMENT_MIX: Replace with exact employment answer.
  MARKET_CONFIRMATION: Yes, that looks right.

  PEOPLE_OWNER_BACKGROUND: Replace with exact owner background answer.
  PEOPLE_OTHER_KEY_PEOPLE: I'm currently the only key person involved in the business.
  PEOPLE_CONFIRMATION: Yes, that looks right.

  FINANCIALS_REVENUE_SETUP: Replace with exact Year-1 revenue answer.
  FINANCIALS_COGS: Replace with exact COGS answer.
  FINANCIALS_PAYROLL: Replace with exact payroll answer.
  FINANCIALS_PAYROLL_DETAIL: Replace with exact payroll-detail answer if needed.
  FINANCIALS_MONTHLY_RENT_EXPENSE: Replace with exact monthly rent answer.
  FINANCIALS_OTHER_OPERATING_EXPENSE: Replace with exact other operating expense answer.
  FINANCIALS_OTHER_MONTHLY_DEBT_PAYMENTS: Replace with exact other monthly debt answer.
  FINANCIALS_CASH_ON_HAND: Replace with exact cash-on-hand answer.
  FINANCIALS_AR_BALANCE: Replace with exact AR balance answer.
  FINANCIALS_AP_BALANCE: Replace with exact AP balance answer.
  FINANCIALS_INVENTORY_BALANCE: Replace with exact inventory balance answer.
  FINANCIALS_CURRENT_CAPEX: Replace with exact current capex answer.
  FINANCIALS_INITIAL_ASSETS: Replace with exact initial assets answer.
  FINANCIALS_INITIAL_LEASE: Replace with exact initial lease answer like 1200,monthly or 0,none.
  FINANCIALS_INITIAL_EQUITY: Replace with exact initial equity answer.
  FINANCIALS_TOTAL_DEBT_OUTSTANDING: Replace with exact total debt answer.
  FINANCIALS_ANNUAL_INTEREST_PAYMENT: Replace with exact annual interest answer.
  FINANCIALS_ANNUAL_PRINCIPAL_PAYMENT: Replace with exact annual principal answer.
  FINANCIALS_OWNER_COMPENSATION: Replace with exact owner compensation answer.
  FINANCIALS_CONFIRMATION: Yes, that's right.

  OVERRIDE_1_FOCUS:
  OVERRIDE_1_CONTAINS:
  OVERRIDE_1_ANSWER:
  """
).strip()


def _parse_key_value_text(text: str) -> Dict[str, str]:
  values: Dict[str, str] = {}
  for raw_line in str(text or "").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    if ":" not in line:
      continue
    key, value = line.split(":", 1)
    values[key.strip().upper()] = value.strip()
  return values


def _split_aliases(value: str) -> List[str]:
  items = [item.strip() for item in str(value or "").split(",")]
  return [item for item in items if item]


def _build_spec(values: Dict[str, str]) -> Dict[str, Any]:
  products: List[Dict[str, Any]] = []
  for index in range(1, 10):
    prefix = f"PRODUCT_{index}_"
    name = values.get(f"{prefix}NAME", "").strip()
    if not name:
      continue
    products.append(
      {
        "product_name": name,
        "aliases": _split_aliases(values.get(f"{prefix}ALIASES", "")),
        "unit_definition": values.get(f"{prefix}UNIT_DEFINITION", "").strip(),
        "capacity": values.get(f"{prefix}CAPACITY", "").strip(),
        "utilization": values.get(f"{prefix}UTILIZATION", "").strip(),
        "price": values.get(f"{prefix}PRICE", "").strip(),
      }
    )

  overrides: List[Dict[str, str]] = []
  for index in range(1, 10):
    focus = values.get(f"OVERRIDE_{index}_FOCUS", "").strip()
    contains = values.get(f"OVERRIDE_{index}_CONTAINS", "").strip()
    answer = values.get(f"OVERRIDE_{index}_ANSWER", "").strip()
    if focus or contains or answer:
      overrides.append({"focus": focus, "contains": contains, "answer": answer})

  return {
    "bootstrap": {
      "business_name": values.get("BUSINESS_NAME", "").strip(),
      "business_start_date": values.get("BUSINESS_START_DATE", "").strip(),
      "address": values.get("ADDRESS", "").strip(),
      "address_street": values.get("ADDRESS_STREET", "").strip(),
      "address_city": values.get("ADDRESS_CITY", "").strip(),
      "address_state": values.get("ADDRESS_STATE", "").strip(),
      "address_zip": values.get("ADDRESS_ZIP", "").strip(),
      "address_country": values.get("ADDRESS_COUNTRY", "").strip(),
    },
    "ops": {
      "business_description": values.get("OPS_BUSINESS_DESCRIPTION", "").strip(),
      "customer_type": values.get("OPS_CUSTOMER_TYPE", "").strip(),
      "products_confirmed": values.get("OPS_PRODUCTS_CONFIRMED", "").strip(),
      "legal_entity": values.get("OPS_LEGAL_ENTITY", "").strip(),
      "delivery_method": values.get("OPS_DELIVERY_METHOD", "").strip(),
      "fulfillment_confirmation": values.get("OPS_FULFILLMENT_CONFIRMATION", "").strip(),
      "sales_channel": values.get("OPS_SALES_CHANNEL", "").strip(),
      "geography": values.get("OPS_GEOGRAPHY", "").strip(),
      "growth_lever": values.get("OPS_GROWTH_LEVER", "").strip(),
      "competitive_advantage": values.get("OPS_COMPETITIVE_ADVANTAGE", "").strip(),
      "goal_12_months": values.get("OPS_GOAL_12_MONTHS", "").strip(),
      "confirmation": values.get("OPS_CONFIRMATION", "").strip(),
      "products": products,
    },
    "market": {
      "gender": values.get("MARKET_GENDER", "").strip(),
      "age_range": values.get("MARKET_AGE_RANGE", "").strip(),
      "income_range": values.get("MARKET_INCOME_RANGE", "").strip(),
      "education": values.get("MARKET_EDUCATION", "").strip(),
      "profile_detail_choice": values.get("MARKET_PROFILE_DETAIL_CHOICE", "").strip(),
      "employment_mix": values.get("MARKET_EMPLOYMENT_MIX", "").strip(),
      "confirmation": values.get("MARKET_CONFIRMATION", "").strip(),
    },
    "people": {
      "owner_background": values.get("PEOPLE_OWNER_BACKGROUND", "").strip(),
      "other_key_people": values.get("PEOPLE_OTHER_KEY_PEOPLE", "").strip(),
      "confirmation": values.get("PEOPLE_CONFIRMATION", "").strip(),
    },
    "financials": {
      "revenue_setup": values.get("FINANCIALS_REVENUE_SETUP", "").strip(),
      "cogs": values.get("FINANCIALS_COGS", "").strip(),
      "payroll": values.get("FINANCIALS_PAYROLL", "").strip(),
      "payroll_detail": values.get("FINANCIALS_PAYROLL_DETAIL", "").strip(),
      "monthly_rent_expense": values.get("FINANCIALS_MONTHLY_RENT_EXPENSE", "").strip(),
      "other_operating_expense": values.get("FINANCIALS_OTHER_OPERATING_EXPENSE", "").strip(),
      "other_monthly_debt_payments": values.get("FINANCIALS_OTHER_MONTHLY_DEBT_PAYMENTS", "").strip(),
      "cash_on_hand": values.get("FINANCIALS_CASH_ON_HAND", "").strip(),
      "ar_balance": values.get("FINANCIALS_AR_BALANCE", "").strip(),
      "ap_balance": values.get("FINANCIALS_AP_BALANCE", "").strip(),
      "inventory_balance": values.get("FINANCIALS_INVENTORY_BALANCE", "").strip(),
      "current_capex": values.get("FINANCIALS_CURRENT_CAPEX", "").strip(),
      "initial_assets": values.get("FINANCIALS_INITIAL_ASSETS", "").strip(),
      "initial_lease": values.get("FINANCIALS_INITIAL_LEASE", "").strip(),
      "initial_equity": values.get("FINANCIALS_INITIAL_EQUITY", "").strip(),
      "total_debt_outstanding": values.get("FINANCIALS_TOTAL_DEBT_OUTSTANDING", "").strip(),
      "annual_interest_payment": values.get("FINANCIALS_ANNUAL_INTEREST_PAYMENT", "").strip(),
      "annual_principal_payment": values.get("FINANCIALS_ANNUAL_PRINCIPAL_PAYMENT", "").strip(),
      "owner_compensation": values.get("FINANCIALS_OWNER_COMPENSATION", "").strip(),
      "confirmation": values.get("FINANCIALS_CONFIRMATION", "").strip(),
    },
    "fallback": {
      "ops": [],
      "market": [],
      "people": [],
      "financials": [],
    },
    "overrides": overrides,
  }


def main() -> int:
  parser = argparse.ArgumentParser(description="Run a controlled intake simulation from pasted plain text.")
  parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
  parser.add_argument("--max-turns", type=int, default=80)
  parser.add_argument("--output-dir", default=_SCRIPTED._SHARED.DEFAULT_TEST_RUNS_DIR)
  parser.add_argument("--persisted-output-dir", default=_SCRIPTED._SHARED.DEFAULT_TEST_RUNS_DATA_DIR)
  parser.add_argument("--print-template", action="store_true", help="Print the paste template and exit.")
  args = parser.parse_args()

  if args.print_template:
    print(TEMPLATE)
    return 0

  raw = sys.stdin.read()
  if not str(raw or "").strip():
    print("Paste the filled template into stdin. Use --print-template to see the format.", file=sys.stderr)
    return 2

  values = _parse_key_value_text(raw)
  spec = _build_spec(values)
  return _SCRIPTED._run_spec(
    spec_path="<pasted_scenario>",
    spec=spec,
    base_url=str(args.base_url or "").rstrip("/"),
    max_turns=int(args.max_turns),
    output_dir=str(args.output_dir),
    persisted_output_dir=str(args.persisted_output_dir),
  )


if __name__ == "__main__":
  raise SystemExit(main())
