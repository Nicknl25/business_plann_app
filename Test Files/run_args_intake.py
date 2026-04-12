import argparse
import copy
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


THIS_DIR = Path(__file__).resolve().parent
PYTHON_DIR = THIS_DIR.parent / "python"
CLIENT_DIR = PYTHON_DIR / "client_intake_and_finmo"
SCRIPTED_RUNNER_PATH = THIS_DIR / "run_scripted_intake.py"
DUAL_RUNNER_PATH = THIS_DIR / "run_dual_agent_intake.py"
INTAKE_SUBMISSION_PATH = CLIENT_DIR / "intake_submission.py"
INTAKE_DRAFT_PATH = CLIENT_DIR / "intake_consult_draft.py"
REALISM_MEMO_PATH = CLIENT_DIR / "realism_memo.py"

for extra_path in (str(PYTHON_DIR), str(CLIENT_DIR)):
  if extra_path not in sys.path:
    sys.path.insert(0, extra_path)


def _load_module(path: Path, name: str):
  spec = importlib.util.spec_from_file_location(name, str(path))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load module from {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


_SCRIPTED = _load_module(SCRIPTED_RUNNER_PATH, "run_scripted_intake_shared_args")
_DUAL = _load_module(DUAL_RUNNER_PATH, "run_dual_agent_intake_shared_args")
_SUBMISSION = _load_module(INTAKE_SUBMISSION_PATH, "intake_submission_shared_args")
_DRAFT = _load_module(INTAKE_DRAFT_PATH, "intake_consult_draft_shared_args")
_REALISM = _load_module(REALISM_MEMO_PATH, "realism_memo_shared_args")


KEY_HELP = """
Supported keys for `--set key=value`:

bootstrap.business_name
bootstrap.business_start_date
bootstrap.address
bootstrap.address_street
bootstrap.address_city
bootstrap.address_state
bootstrap.address_zip
bootstrap.address_country

ops.business_description
ops.customer_type
ops.products_confirmed
ops.legal_entity
ops.delivery_method
ops.fulfillment_confirmation
ops.sales_channel
ops.geography
ops.growth_lever
ops.competitive_advantage
ops.goal_12_months
ops.confirmation

market.gender
market.age_range
market.income_range
market.education
market.profile_detail_choice
market.employment_mix
market.confirmation

people.owner_background
people.other_key_people
people.confirmation

financials.revenue_setup
financials.cogs
financials.payroll
financials.payroll_detail
financials.monthly_rent_expense
financials.other_operating_expense
financials.other_monthly_debt_payments
financials.cash_on_hand
financials.ar_balance
financials.ap_balance
financials.inventory_balance
financials.current_capex
financials.initial_assets
financials.initial_lease
financials.initial_equity
financials.total_debt_outstanding
financials.annual_interest_payment
financials.annual_principal_payment
financials.owner_compensation
financials.confirmation

product1.name
product1.aliases
product1.unit_definition
product1.cadence
product1.capacity
product1.capacity_value
product1.capacity_period
product1.utilization
product1.utilization_value
product1.price
product1.price_value

product2.name
product2.aliases
product2.unit_definition
product2.cadence
product2.capacity
product2.capacity_value
product2.capacity_period
product2.utilization
product2.utilization_value
product2.price
product2.price_value

product3.name
product3.aliases
product3.unit_definition
product3.cadence
product3.capacity
product3.capacity_value
product3.capacity_period
product3.utilization
product3.utilization_value
product3.price
product3.price_value

Use the same pattern for product4, product5, etc.

override1.focus
override1.contains
override1.answer

Use the same pattern for override2, override3, etc.
""".strip()


def _blank_spec() -> Dict[str, Any]:
  return {
    "bootstrap": {
      "business_name": "",
      "business_start_date": "",
      "address": "",
      "address_street": "",
      "address_city": "",
      "address_state": "",
      "address_zip": "",
      "address_country": "",
    },
    "ops": {
      "business_description": "",
      "customer_type": "",
      "products_confirmed": "Yes, track those as separate products.",
      "legal_entity": "",
      "delivery_method": "",
      "fulfillment_confirmation": "Yes, that's accurate.",
      "sales_channel": "",
      "geography": "",
      "growth_lever": "",
      "competitive_advantage": "",
      "goal_12_months": "",
      "confirmation": "Yes, that's correct.",
      "products": [],
    },
    "market": {
      "gender": "",
      "age_range": "",
      "income_range": "",
      "education": "",
      "profile_detail_choice": "",
      "employment_mix": "",
      "confirmation": "Yes, that looks right.",
    },
    "people": {
      "owner_background": "",
      "other_key_people": "I'm currently the only key person involved in the business.",
      "confirmation": "Yes, that looks right.",
    },
    "financials": {
      "revenue_setup": "",
      "cogs": "",
      "payroll": "",
      "payroll_detail": "",
      "monthly_rent_expense": "",
      "other_operating_expense": "",
      "other_monthly_debt_payments": "",
      "cash_on_hand": "",
      "ar_balance": "",
      "ap_balance": "",
      "inventory_balance": "",
      "current_capex": "",
      "initial_assets": "",
      "initial_lease": "",
      "initial_equity": "",
      "total_debt_outstanding": "",
      "annual_interest_payment": "",
      "annual_principal_payment": "",
      "owner_compensation": "",
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


def _ensure_product(spec: Dict[str, Any], index: int) -> Dict[str, Any]:
  products = spec["ops"]["products"]
  while len(products) < index:
    products.append(
      {
        "product_name": "",
        "aliases": [],
        "unit_definition": "",
        "cadence": "",
        "capacity": "",
        "capacity_value": "",
        "capacity_period": "",
        "utilization": "",
        "utilization_value": "",
        "price": "",
        "price_value": "",
      }
    )
  return products[index - 1]


def _ensure_override(spec: Dict[str, Any], index: int) -> Dict[str, Any]:
  overrides = spec["overrides"]
  while len(overrides) < index:
    overrides.append({"focus": "", "contains": "", "answer": ""})
  return overrides[index - 1]


def _apply_set(spec: Dict[str, Any], key: str, value: str) -> None:
  raw_key = str(key or "").strip()
  if not raw_key or "=" in raw_key:
    raise RuntimeError(f"Invalid key: {raw_key}")
  parts = raw_key.split(".")
  if len(parts) == 2 and parts[0] in {"bootstrap", "ops", "market", "people", "financials"}:
    spec[parts[0]][parts[1]] = value
    return
  if len(parts) == 2 and parts[0].startswith("product") and parts[0][7:].isdigit():
    product = _ensure_product(spec, int(parts[0][7:]))
    field = parts[1]
    if field == "name":
      product["product_name"] = value
    elif field == "aliases":
      product["aliases"] = [item.strip() for item in value.split(",") if item.strip()]
    elif field in {"unit_definition", "cadence", "capacity", "capacity_value", "capacity_period", "utilization", "utilization_value", "price", "price_value"}:
      product[field] = value
    else:
      raise RuntimeError(f"Unsupported product field: {raw_key}")
    return
  if len(parts) == 2 and parts[0].startswith("override") and parts[0][8:].isdigit():
    override = _ensure_override(spec, int(parts[0][8:]))
    if parts[1] not in {"focus", "contains", "answer"}:
      raise RuntimeError(f"Unsupported override field: {raw_key}")
    override[parts[1]] = value
    return
  raise RuntimeError(f"Unsupported key: {raw_key}")


def _parse_set_arg(raw: str) -> Tuple[str, str]:
  if "=" not in str(raw or ""):
    raise RuntimeError(f"--set must be key=value, got: {raw}")
  key, value = str(raw).split("=", 1)
  return key.strip(), value.strip()


def _parse_answers_blob(raw: str) -> List[Tuple[str, str]]:
  text = str(raw or "").strip()
  if not text:
    return []
  pairs: List[Tuple[str, str]] = []
  normalized = text.replace("\r\n", "\n")
  if ";;" in normalized:
    chunks = [item.strip() for item in normalized.split(";;") if item.strip()]
  else:
    chunks = [line.strip() for line in normalized.split("\n") if line.strip()]
  for chunk in chunks:
    pairs.append(_parse_set_arg(chunk))
  return pairs


def _prune_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
  cleaned = copy.deepcopy(spec)
  cleaned["ops"]["products"] = [
    item for item in cleaned["ops"]["products"]
    if str(item.get("product_name") or "").strip()
  ]
  cleaned["overrides"] = [
    item for item in cleaned["overrides"]
    if any(str(item.get(key) or "").strip() for key in ("focus", "contains", "answer"))
  ]
  return cleaned


def _bootstrap_defaults(*, seed: str, model: str, business_start_date_override: str) -> Dict[str, str]:
  api_key = os.getenv("OPENAI_API_KEY", "").strip()
  if not api_key:
    return {}
  agent = _DUAL.ClientAgent(
    api_key=api_key,
    model=model,
    seed=seed,
    business_start_date_override=business_start_date_override or None,
  )
  bootstrap = agent.bootstrap()
  return {
    "business_name": str(bootstrap.business_name or "").strip(),
    "business_start_date": str(bootstrap.business_start_date or "").strip(),
    "address": str(bootstrap.address or "").strip(),
    "address_street": str(bootstrap.address_street or "").strip(),
    "address_city": str(bootstrap.address_city or "").strip(),
    "address_state": str(bootstrap.address_state or "").strip(),
    "address_zip": str(bootstrap.address_zip or "").strip(),
    "address_country": str(bootstrap.address_country or "").strip(),
  }


def _text(value: Any) -> str:
  return str(value or "").strip()


def _normalize_consumer_type(raw: str) -> str:
  value = _text(raw).lower()
  if not value:
    return "consumer"
  if "mix" in value:
    return "mixed"
  has_consumer = any(token in value for token in ("consumer", "individual", "household", "patient", "member"))
  has_b2b = any(token in value for token in ("business", "b2b", "company", "employer", "office", "corporate"))
  if has_consumer and has_b2b:
    return "mixed"
  if has_b2b and not has_consumer:
    return "b2b"
  return "consumer"


def _normalize_scope(raw: str) -> str:
  value = _text(raw).lower()
  if "international" in value or "global" in value:
    return "international"
  if "national" in value or "country" in value or "statewide" in value:
    return "national"
  if "regional" in value or "multi-state" in value:
    return "regional"
  return "local"


def _normalize_sales_modality(raw: str) -> str:
  value = _text(raw).lower()
  has_online = any(token in value for token in ("online", "digital", "web", "site", "website", "app"))
  has_physical = any(token in value for token in ("in person", "on-site", "onsite", "travel", "visit", "ship", "deliver", "pickup", "store"))
  if has_online and has_physical:
    return "hybrid"
  if has_online:
    return "online"
  return "physical"


def _normalize_shipping_method(raw: str) -> str:
  value = _text(raw).lower()
  if "ship" in value:
    return "shipping"
  if any(token in value for token in ("home", "office", "client", "travel", "on-site", "onsite", "visit")):
    return "in-person on-site service"
  return _text(raw) or "in-person delivery"


def _derive_capacity_driver(raw: str) -> str:
  value = _text(raw).lower()
  if any(token in value for token in ("staff", "provider", "hire", "labor", "hours", "time", "team")):
    return "labor"
  if any(token in value for token in ("system", "automation", "software", "workflow", "platform")):
    return "system"
  if any(token in value for token in ("demand", "lead", "marketing", "sales", "bookings")):
    return "demand"
  return "labor"


def _extract_first_number(raw: Any) -> Optional[float]:
  if raw is None:
    return None
  if isinstance(raw, (int, float)) and not isinstance(raw, bool):
    return float(raw)
  text = _text(raw).replace(",", "")
  if not text:
    return None
  import re
  match = re.search(r"-?\d+(?:\.\d+)?", text)
  if not match:
    return None
  try:
    return float(match.group(0))
  except Exception:
    return None


def _extract_ratio(raw: Any) -> Optional[float]:
  text = _text(raw)
  if not text:
    return None
  number = _extract_first_number(text)
  if number is None:
    return None
  lowered = text.lower()
  if "%" in lowered or "percent" in lowered:
    return round(max(0.0, number) / 100.0, 6)
  if number > 1.0:
    return round(max(0.0, number) / 100.0, 6)
  return round(max(0.0, number), 6)


def _infer_cadence(raw: str) -> str:
  value = _text(raw).lower()
  if "day" in value:
    return "daily"
  if "week" in value:
    return "weekly"
  if "month" in value:
    return "monthly"
  if "quarter" in value:
    return "quarterly"
  if "year" in value or "annual" in value:
    return "yearly"
  return "weekly"


def _normalize_cadence_value(raw: str, *, default: str = "weekly") -> str:
  value = _text(raw).lower()
  if value in {"day", "daily"}:
    return "daily"
  if value in {"week", "weekly"}:
    return "weekly"
  if value in {"month", "monthly"}:
    return "monthly"
  if value in {"quarter", "quarterly"}:
    return "quarterly"
  if value in {"year", "yearly", "annual", "annually"}:
    return "yearly"
  inferred = _infer_cadence(value)
  return inferred or default


def _capacity_fields(raw: str, *, exact_value: Any = None, exact_period: str = "") -> Dict[str, float]:
  amount = max(0.0, _extract_first_number(exact_value) if exact_value not in (None, "") else (_extract_first_number(raw) or 0.0))
  cadence = _normalize_cadence_value(exact_period, default=_infer_cadence(raw))
  if cadence == "monthly":
    return {"units_per_month_capacity": round(amount, 6), "units_per_period_capacity": round(amount, 6), "operating_periods_per_year": 12.0}
  if cadence == "quarterly":
    return {"units_per_period_capacity": round(amount, 6), "operating_periods_per_year": 4.0}
  if cadence == "yearly":
    return {"units_per_period_capacity": round(amount, 6), "operating_periods_per_year": 1.0}
  if cadence == "daily":
    return {"units_per_period_capacity": round(amount, 6), "operating_periods_per_year": 365.0}
  return {"units_per_week_capacity": round(amount, 6), "units_per_period_capacity": round(amount, 6), "operating_periods_per_year": 52.0}


def _normalized_legal_entity(raw: str) -> str:
  return _text(raw).rstrip(".") or "LLC"


def _normalized_business_stage(start_date_raw: str) -> str:
  raw = _text(start_date_raw)
  if not raw:
    return "operating"
  try:
    start = datetime.strptime(raw, "%m/%d/%Y").date()
  except Exception:
    return "operating"
  today = datetime.now().date()
  return "operating" if start <= today else "pre-revenue"


def _product_price(item: Dict[str, Any]) -> float:
  explicit = item.get("price_value")
  return round(max(0.0, _extract_first_number(explicit) if explicit not in (None, "") else (_extract_first_number(item.get("price")) or 0.0)), 6)


def _product_utilization(item: Dict[str, Any]) -> float:
  explicit = item.get("utilization_value")
  parsed = _extract_ratio(explicit) if explicit not in (None, "") else _extract_ratio(item.get("utilization"))
  return parsed or 0.0


def _product_cadence(item: Dict[str, Any]) -> str:
  explicit = _text(item.get("cadence"))
  if explicit:
    return _normalize_cadence_value(explicit)
  return _normalize_cadence_value(_text(item.get("capacity")) or _text(item.get("unit_definition")))


def _build_operating_model(spec: Dict[str, Any]) -> Dict[str, Any]:
  bootstrap = spec.get("bootstrap") if isinstance(spec.get("bootstrap"), dict) else {}
  ops = spec.get("ops") if isinstance(spec.get("ops"), dict) else {}
  products = ops.get("products") if isinstance(ops.get("products"), list) else []
  consumer_type = _normalize_consumer_type(_text(ops.get("customer_type")))
  geography = _text(ops.get("geography"))
  first_product = products[0] if products and isinstance(products[0], dict) else {}
  first_capacity = _capacity_fields(
    _text(first_product.get("capacity")),
    exact_value=first_product.get("capacity_value"),
    exact_period=_text(first_product.get("capacity_period")) or _text(first_product.get("cadence")),
  )
  first_price = _product_price(first_product)
  first_utilization = _product_utilization(first_product)

  lob_products: List[Dict[str, Any]] = []
  for item in products:
    if not isinstance(item, dict):
      continue
    product_name = _text(item.get("product_name")) or "Product"
    unit_definition = _text(item.get("unit_definition"))
    capacity_fields = _capacity_fields(
      _text(item.get("capacity")),
      exact_value=item.get("capacity_value"),
      exact_period=_text(item.get("capacity_period")) or _text(item.get("cadence")),
    )
    cadence = _product_cadence(item)
    product_payload: Dict[str, Any] = {
      "product_name": product_name,
      "unit_name": product_name,
      "unit_description": unit_definition,
      "unit_cadence": cadence,
      "unit_price": _product_price(item),
      "utilization_rate": _product_utilization(item),
    }
    product_payload.update(capacity_fields)
    lob_products.append(product_payload)

  if not lob_products:
    raise RuntimeError("At least one product is required.")

  operating_model: Dict[str, Any] = {
    "business_type": "Primary line of business",
    "consumer_type": consumer_type,
    "business_stage": _normalized_business_stage(_text(bootstrap.get("business_start_date"))),
    "unit_name": _text(first_product.get("product_name")) or "Primary product",
    "unit_description": _text(first_product.get("unit_definition")),
    "unit_cadence": _product_cadence(first_product),
    "unit_price": first_price,
    "utilization_rate": first_utilization or 0.0,
    "shipping_method": _normalize_shipping_method(_text(ops.get("delivery_method"))),
    "sales_modality": _normalize_sales_modality(f"{_text(ops.get('delivery_method'))} {_text(ops.get('sales_channel'))}"),
    "geographic_scope": _normalize_scope(geography),
    "geographic_coverage": geography,
    "countries": [_text(bootstrap.get("address_country")) or "USA"],
    "capacity_driver": _derive_capacity_driver(_text(ops.get("growth_lever"))),
    "primary_growth_lever": _text(ops.get("growth_lever")),
    "legal_entity": _normalized_legal_entity(_text(ops.get("legal_entity"))),
    "business_description_summary": _text(ops.get("business_description")),
    "lob_models": [
      {
        "lob_name": "Primary line of business",
        "products": lob_products,
      }
    ],
  }
  operating_model.update(first_capacity)
  return operating_model


def _build_target_market(spec: Dict[str, Any], ops_json: Dict[str, Any]) -> Dict[str, Any]:
  market = spec.get("market") if isinstance(spec.get("market"), dict) else {}
  summary_parts = [
    _text(market.get("gender")),
    _text(market.get("age_range")),
    _text(market.get("income_range")),
    _text(market.get("education")),
    _text(market.get("employment_mix")),
  ]
  summary = "; ".join(part for part in summary_parts if part)
  return {
    "consumer_type": str(ops_json.get("consumer_type") or "consumer"),
    "target_market_summary": summary or "Direct-runner seeded target market.",
    "confidence": 1.0,
  }


def _build_people_json(spec: Dict[str, Any]) -> Dict[str, Any]:
  people = spec.get("people") if isinstance(spec.get("people"), dict) else {}
  owner_background = _text(people.get("owner_background"))
  other_people = _text(people.get("other_key_people"))
  people_list: List[Dict[str, Any]] = []
  if owner_background:
    people_list.append({"name": "Owner", "role": "Owner", "summary": owner_background})
  if other_people and "only key person" not in other_people.lower():
    people_list.append({"name": "Additional team", "role": "Team", "summary": other_people})
  return {
    "people": people_list,
    "key_people_summary": owner_background or other_people or "Direct-runner seeded people context.",
    "confidence": 1.0,
  }


def _build_financials_json(spec: Dict[str, Any]) -> Dict[str, Any]:
  financials = spec.get("financials") if isinstance(spec.get("financials"), dict) else {}
  out: Dict[str, Any] = {
    "financials_summary": _text(financials.get("revenue_setup")) or "Direct-runner seeded financials context.",
    "cogs_total_year1": round(max(0.0, _extract_first_number(financials.get("cogs")) or 0.0), 6),
    "payroll_total_year1": round(max(0.0, _extract_first_number(financials.get("payroll")) or 0.0), 6),
    "monthly_rent_expense": round(max(0.0, _extract_first_number(financials.get("monthly_rent_expense")) or 0.0), 6),
    "other_operating_expense": round(max(0.0, _extract_first_number(financials.get("other_operating_expense")) or 0.0), 6),
    "other_monthly_debt_payments": round(max(0.0, _extract_first_number(financials.get("other_monthly_debt_payments")) or 0.0), 6),
    "cash_on_hand": round(max(0.0, _extract_first_number(financials.get("cash_on_hand")) or 0.0), 6),
    "ar_balance": round(max(0.0, _extract_first_number(financials.get("ar_balance")) or 0.0), 6),
    "ap_balance": round(max(0.0, _extract_first_number(financials.get("ap_balance")) or 0.0), 6),
    "inventory_balance": round(max(0.0, _extract_first_number(financials.get("inventory_balance")) or 0.0), 6),
    "current_capex": round(max(0.0, _extract_first_number(financials.get("current_capex")) or 0.0), 6),
    "initial_assets": round(max(0.0, _extract_first_number(financials.get("initial_assets")) or 0.0), 6),
    "initial_lease": _text(financials.get("initial_lease")),
    "initial_equity": round(max(0.0, _extract_first_number(financials.get("initial_equity")) or 0.0), 6),
    "total_debt_outstanding": round(max(0.0, _extract_first_number(financials.get("total_debt_outstanding")) or 0.0), 6),
    "annual_interest_payment": round(max(0.0, _extract_first_number(financials.get("annual_interest_payment")) or 0.0), 6),
    "annual_principal_payment": round(max(0.0, _extract_first_number(financials.get("annual_principal_payment")) or 0.0), 6),
    "owner_compensation": round(max(0.0, _extract_first_number(financials.get("owner_compensation")) or 0.0), 6),
  }
  return out


def _planning_resolution_payload(spec: Dict[str, Any]) -> Dict[str, Any]:
  return {
    "stage": "intake_complete",
    "status": "completed",
    "resolution_summary": {
      "status": "completed",
      "all_resolved": True,
      "resolved_items": [{"message": "Direct-runner seeded intake completion."}],
      "blocking_items": [],
      "open_items": [],
    },
  }


def _persist_reports(
  *,
  base_url: str,
  output_dir: str,
  persisted_output_dir: str,
  seed: str,
  bootstrap: Any,
  transcript: List[Dict[str, str]],
  draft_id: Optional[str],
  client_id: Optional[str],
  status: str,
  stop_reason: str,
  trace_file_name: str,
) -> None:
  written_at = _DUAL._eastern_now()
  artifact_seed = _DUAL._artifact_seed(seed=seed, draft_id=draft_id)
  path = _DUAL._save_run_report(
    output_dir=output_dir,
    seed=artifact_seed,
    bootstrap=bootstrap,
    transcript=transcript,
    draft_id=draft_id,
    status=status,
    stop_reason=stop_reason,
    written_at=written_at,
  )
  if path:
    print(f"Saved run report: {path}")
  persisted_path = _DUAL._save_persisted_state_report(
    base_url=base_url,
    output_dir=persisted_output_dir,
    seed=artifact_seed,
    bootstrap=bootstrap,
    draft_id=draft_id,
    client_id=client_id,
    status=status,
    stop_reason=stop_reason,
    written_at=written_at,
  )
  if persisted_path:
    print(f"Saved persisted state report: {persisted_path}")
  new_runner_path = _DUAL._save_new_runner_report(
    base_url=base_url,
    output_dir=_DUAL.DEFAULT_NEW_RUNNER_DIR,
    seed=artifact_seed,
    bootstrap=bootstrap,
    draft_id=draft_id,
    written_at=written_at,
  )
  if new_runner_path:
    print(f"Saved New Runner report: {new_runner_path}")
  new_runner_grid_path = _DUAL._save_new_runner_grid_report(
    base_url=base_url,
    output_dir=_DUAL.DEFAULT_NEW_RUNNER_DIR,
    seed=artifact_seed,
    draft_id=draft_id,
    written_at=written_at,
  )
  if new_runner_grid_path:
    print(f"Saved New Runner grid report: {new_runner_grid_path}")
  if trace_file_name:
    print(f"Expected terminal log file: {os.path.join(_DUAL.DEFAULT_TERMINAL_LOGS_DIR, trace_file_name)}")


def _validate_product_count(spec: Dict[str, Any], *, forced_product_count: Optional[int]) -> None:
  if forced_product_count is None:
    return
  ops = spec.get("ops") if isinstance(spec.get("ops"), dict) else {}
  products = ops.get("products") if isinstance(ops.get("products"), list) else []
  actual = sum(1 for item in products if isinstance(item, dict) and _text(item.get("product_name")))
  if actual != forced_product_count:
    raise RuntimeError(f"runner_requires_exactly_{forced_product_count}_products_but_got_{actual}")


def _run_direct_seeded(
  *,
  spec: Dict[str, Any],
  base_url: str,
  output_dir: str,
  persisted_output_dir: str,
  seed: str,
) -> int:
  bootstrap_data = spec["bootstrap"]
  bootstrap = _DUAL.Bootstrap(
    business_name=_text(bootstrap_data.get("business_name")),
    business_start_date=_text(bootstrap_data.get("business_start_date")),
    address=_text(bootstrap_data.get("address")),
    address_street=_text(bootstrap_data.get("address_street")),
    address_city=_text(bootstrap_data.get("address_city")),
    address_state=_text(bootstrap_data.get("address_state")),
    address_zip=_text(bootstrap_data.get("address_zip")),
    address_country=_text(bootstrap_data.get("address_country")),
    private_state="",
  )
  transcript: List[Dict[str, str]] = []
  print(f"Bootstrapped business: {bootstrap.business_name}")

  session = _DUAL._post_json(f"{base_url}/api/intake-consult/session", {})
  draft_id = str(session.get("draft_id") or "").strip()
  client_id = str(session.get("client_id") or "").strip()
  if not draft_id:
    raise RuntimeError(f"Failed to create draft session: {session}")
  trace_file_name = _DUAL._build_run_artifact_filename(
    seed=_DUAL._artifact_seed(seed=seed, draft_id=draft_id),
    written_at=_DUAL._eastern_now(),
  )

  ops_json = _build_operating_model(spec)
  market_json = _build_target_market(spec, ops_json)
  people_json = _build_people_json(spec)
  financials_json = _build_financials_json(spec)
  planning_run_json = _planning_resolution_payload(spec)
  realism_memo_json = _REALISM.generate_realism_memo_payload_safe(
    ops_json=ops_json,
    financials_json=financials_json,
  )
  business_facts = {
    "name": bootstrap.business_name,
    "address": bootstrap.address,
    "address_street": bootstrap.address_street,
    "address_city": bootstrap.address_city,
    "address_state": bootstrap.address_state,
    "address_zip": bootstrap.address_zip,
    "address_country": bootstrap.address_country,
    "start_date": bootstrap.business_start_date,
  }

  conn = _SUBMISSION.get_mysql_connection()
  try:
    _DRAFT.append_messages(
      conn,
      draft_id=draft_id,
      new_messages=[
        {"role": "assistant", "content": "Direct-runner draft seeded from explicit CLI fields."},
      ],
      operating_model_json=ops_json,
      target_market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      realism_memo_json=realism_memo_json,
      planning_run_json=planning_run_json,
      active_focus="done",
      confirmations={"ops": True, "market": True, "people": True, "financials": True},
      business_facts=business_facts,
      status="completed",
      completed=True,
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass

  transcript.append({"role": "system", "content": "Draft seeded directly from CLI fields."})
  print("Simulation completed.")
  trace_headers = {
    "X-Planning-Trace-Run-Name": trace_file_name,
    "X-Planning-Trace-Reset": "1",
  }
  system_run_response = _DUAL._post_json(
    f"{base_url}/api/intake-consult/system-run",
    {"draft_id": draft_id, "client_id": client_id},
    timeout=None,
    headers=trace_headers,
  )
  system_message = _text(system_run_response.get("assistant_message")) or "System run complete."
  transcript.append({"role": "assistant", "content": system_message, "focus": "system"})
  print(system_message)
  draft = _DUAL._get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
  realism_flags = _DUAL._realism_final_flags_from_draft(draft)
  print(
    "Final flags:",
    json.dumps(
      {
        "ops_confirmed": draft.get("ops_confirmed"),
        "market_confirmed": draft.get("market_confirmed"),
        "people_confirmed": draft.get("people_confirmed"),
        "financials_confirmed": draft.get("financials_confirmed"),
        **realism_flags,
      },
      ensure_ascii=False,
    ),
  )
  print(f"Draft ID: {draft_id}")
  _persist_reports(
    base_url=base_url,
    output_dir=output_dir,
    persisted_output_dir=persisted_output_dir,
    seed=seed,
    bootstrap=bootstrap,
    transcript=transcript,
    draft_id=draft_id,
    client_id=client_id,
    status="completed",
    stop_reason="system run complete",
    trace_file_name=trace_file_name,
  )
  return 0


def main(argv: Optional[List[str]] = None, *, forced_product_count: Optional[int] = None) -> int:
  _SCRIPTED._SHARED._load_env()
  parser = argparse.ArgumentParser(
    description="Run a controlled intake simulation with one-line CLI overrides."
  )
  parser.add_argument("seed", nargs="?", default="", help="Plain-English business seed, same style as run_dual_agent_intake.py")
  parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
  parser.add_argument("--model", default=os.getenv("INTAKE_SIM_MODEL", "gpt-4.1-mini"))
  parser.add_argument("--max-turns", type=int, default=80)
  parser.add_argument("--business-start-date", default="")
  parser.add_argument("--output-dir", default=_SCRIPTED._SHARED.DEFAULT_TEST_RUNS_DIR)
  parser.add_argument("--persisted-output-dir", default=_SCRIPTED._SHARED.DEFAULT_TEST_RUNS_DATA_DIR)
  parser.add_argument("--set", dest="sets", action="append", default=[], help="Override as key=value. Use --print-keys to see supported keys.")
  parser.add_argument("--answers", default="", help="Single quoted blob of key=value pairs separated by ';;'.")
  parser.add_argument("--print-keys", action="store_true", help="Print supported --set keys and exit.")
  args = parser.parse_args(argv)

  if args.print_keys:
    print(KEY_HELP)
    return 0

  if not str(args.seed or "").strip():
    parser.error("seed is required unless --print-keys is used")

  spec = _blank_spec()
  for raw in args.sets:
    key, value = _parse_set_arg(raw)
    _apply_set(spec, key, value)
  for key, value in _parse_answers_blob(args.answers):
    _apply_set(spec, key, value)

  if str(args.business_start_date or "").strip():
    spec["bootstrap"]["business_start_date"] = str(args.business_start_date).strip()

  required_bootstrap = (
    "business_name",
    "business_start_date",
    "address",
    "address_street",
    "address_city",
    "address_state",
    "address_zip",
    "address_country",
  )
  missing_bootstrap = [key for key in required_bootstrap if not _text(spec["bootstrap"].get(key))]
  if missing_bootstrap:
    bootstrap_defaults = _bootstrap_defaults(
      seed=str(args.seed),
      model=str(args.model),
      business_start_date_override=str(args.business_start_date or "").strip(),
    )
    for key, value in bootstrap_defaults.items():
      if not _text(spec["bootstrap"].get(key)):
        spec["bootstrap"][key] = value

  spec = _prune_spec(spec)
  _validate_product_count(spec, forced_product_count=forced_product_count)
  return _run_direct_seeded(
    spec=spec,
    base_url=str(args.base_url or "").rstrip("/"),
    output_dir=str(args.output_dir),
    persisted_output_dir=str(args.persisted_output_dir),
    seed=str(args.seed).strip(),
  )


if __name__ == "__main__":
  raise SystemExit(main())
