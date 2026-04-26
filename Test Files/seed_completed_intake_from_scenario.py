import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
PYTHON_DIR = ROOT / "python"
CLIENT_DIR = PYTHON_DIR / "client_intake_and_finmo"
RUN_ARGS_PATH = THIS_DIR / "run_args_intake.py"
FINANCIALS_YEAR1_PATH = CLIENT_DIR / "financials_year1.py"
PERSISTED_RUNNER_PATH = THIS_DIR / "run_persisted_system_run.py"

for extra_path in (str(PYTHON_DIR), str(CLIENT_DIR), str(THIS_DIR)):
  if extra_path not in sys.path:
    sys.path.insert(0, extra_path)


def _load_module(path: Path, name: str):
  spec = importlib.util.spec_from_file_location(name, str(path))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load module from {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


_ARGS = _load_module(RUN_ARGS_PATH, "run_args_intake_seed_completed")
_YEAR1 = _load_module(FINANCIALS_YEAR1_PATH, "financials_year1_seed_completed")


REQUIRED_SCALAR_PATHS = (
  "bootstrap.business_name",
  "bootstrap.business_start_date",
  "bootstrap.address",
  "bootstrap.address_street",
  "bootstrap.address_city",
  "bootstrap.address_state",
  "bootstrap.address_zip",
  "bootstrap.address_country",
  "ops.business_description",
  "ops.customer_type",
  "ops.products_confirmed",
  "ops.legal_entity",
  "ops.delivery_method",
  "ops.fulfillment_confirmation",
  "ops.sales_channel",
  "ops.geography",
  "ops.growth_lever",
  "ops.competitive_advantage",
  "ops.goal_12_months",
  "ops.confirmation",
  "market.gender",
  "market.age_range",
  "market.income_range",
  "market.education",
  "market.profile_detail_choice",
  "market.employment_mix",
  "market.confirmation",
  "people.owner_background",
  "people.other_key_people",
  "people.confirmation",
  "financials.revenue_setup",
  "financials.cogs",
  "financials.payroll",
  "financials.payroll_detail",
  "financials.monthly_rent_expense",
  "financials.other_operating_expense",
  "financials.other_monthly_debt_payments",
  "financials.cash_on_hand",
  "financials.ar_balance",
  "financials.ap_balance",
  "financials.inventory_balance",
  "financials.current_capex",
  "financials.initial_assets",
  "financials.initial_lease",
  "financials.initial_equity",
  "financials.total_debt_outstanding",
  "financials.annual_interest_payment",
  "financials.annual_principal_payment",
  "financials.owner_compensation",
  "financials.cash_strategy",
  "financials.confirmation",
)

REQUIRED_PRODUCT_FIELDS = (
  "product_name",
  "aliases",
  "unit_definition",
  "cadence",
  "capacity",
  "capacity_value",
  "capacity_period",
  "utilization",
  "utilization_value",
  "price",
  "price_value",
)

VAGUE_MARKERS = (
  "appropriate",
  "realistic",
  "use industry",
  "as needed",
  "tbd",
  "unknown",
  "not sure",
  "roughly",
  "about",
  "around",
  "large established",
)

EXTRA_FINANCIAL_FIELDS = {
  "cash_strategy",
  "cogs_total_year1",
  "cogs_percent",
  "current_num_employees",
  "maintenance_capex_rate",
  "starting_ppe",
}

EXTRA_KEY_HELP = """
Additional completed-intake seed keys:

financials.cash_strategy
financials.cogs_total_year1
financials.cogs_percent
financials.current_num_employees
financials.maintenance_capex_rate
financials.starting_ppe

milestone1.description
milestone1.timing
milestone1.timing_months_max

Use the same milestone pattern for milestone2, milestone3, etc.
""".strip()


def _text(value: Any) -> str:
  return str(value or "").strip()


def _get_path(data: Dict[str, Any], path: str) -> Any:
  cur: Any = data
  for part in path.split("."):
    if not isinstance(cur, dict):
      return None
    cur = cur.get(part)
  return cur


def _load_json(path: Path) -> Dict[str, Any]:
  with path.open("r", encoding="utf-8") as fh:
    data = json.load(fh)
  if not isinstance(data, dict):
    raise RuntimeError("scenario_file_must_contain_json_object")
  return data


def _ensure_milestone(spec: Dict[str, Any], index: int) -> Dict[str, Any]:
  ops = spec.setdefault("ops", {})
  milestones = ops.setdefault("milestones", [])
  while len(milestones) < index:
    milestones.append({"description": "", "timing": "", "timing_months_max": ""})
  return milestones[index - 1]


def _apply_seed_set(spec: Dict[str, Any], key: str, value: str) -> None:
  raw_key = str(key or "").strip()
  parts = raw_key.split(".")
  if len(parts) == 2 and parts[0] == "financials" and parts[1] in EXTRA_FINANCIAL_FIELDS:
    spec.setdefault("financials", {})[parts[1]] = value
    return
  if len(parts) == 2 and parts[0].startswith("milestone") and parts[0][9:].isdigit():
    milestone = _ensure_milestone(spec, int(parts[0][9:]))
    if parts[1] not in {"description", "timing", "timing_months_max"}:
      raise RuntimeError(f"Unsupported milestone field: {raw_key}")
    milestone[parts[1]] = value
    return
  if len(parts) == 3 and parts[0] == "ops" and parts[1].startswith("milestone") and parts[1][9:].isdigit():
    milestone = _ensure_milestone(spec, int(parts[1][9:]))
    if parts[2] not in {"description", "timing", "timing_months_max"}:
      raise RuntimeError(f"Unsupported milestone field: {raw_key}")
    milestone[parts[2]] = value
    return
  _ARGS._apply_set(spec, key, value)


def _load_spec(path: Optional[Path], overrides: List[str], *, scenario_prompt: str = "") -> Dict[str, Any]:
  spec = _ARGS._blank_spec()
  if scenario_prompt:
    spec["seed_prompt"] = scenario_prompt

  scenario: Dict[str, Any] = {}
  if path is not None:
    scenario = _load_json(path)
    if _text(scenario.get("seed_prompt")) and not scenario_prompt:
      spec["seed_prompt"] = _text(scenario.get("seed_prompt"))

    for section in ("bootstrap", "ops", "market", "people", "financials"):
      value = scenario.get(section)
      if isinstance(value, dict):
        spec[section].update(value)

    products = scenario.get("products")
    if products is None and isinstance(scenario.get("ops"), dict):
      products = scenario["ops"].get("products")
    if isinstance(products, list):
      spec["ops"]["products"] = products

  for raw in overrides:
    key, value = _ARGS._parse_set_arg(raw)
    _apply_seed_set(spec, key, value)

  return _ARGS._prune_spec(spec)


def _validate_complete_spec(spec: Dict[str, Any]) -> None:
  errors: List[str] = []
  for path in REQUIRED_SCALAR_PATHS:
    value = _get_path(spec, path)
    if not _text(value):
      errors.append(f"missing_required_answer:{path}")

  products = spec.get("ops", {}).get("products")
  if not isinstance(products, list) or not products:
    errors.append("missing_required_answer:ops.products")
  else:
    for idx, product in enumerate(products, start=1):
      if not isinstance(product, dict):
        errors.append(f"invalid_product:{idx}")
        continue
      for field in REQUIRED_PRODUCT_FIELDS:
        value = product.get(field)
        if field == "aliases":
          if not isinstance(value, list) or not value:
            errors.append(f"missing_required_answer:product{idx}.{field}")
          continue
        if not _text(value):
          errors.append(f"missing_required_answer:product{idx}.{field}")

  milestones = spec.get("ops", {}).get("milestones")
  if not isinstance(milestones, list) or not milestones:
    errors.append("missing_required_answer:ops.milestones")
  else:
    for idx, item in enumerate(milestones, start=1):
      if not isinstance(item, dict):
        errors.append(f"invalid_milestone:{idx}")
        continue
      for field in ("description", "timing", "timing_months_max"):
        if not _text(item.get(field)):
          errors.append(f"missing_required_answer:ops.milestones[{idx}].{field}")

  for path in REQUIRED_SCALAR_PATHS:
    value = _text(_get_path(spec, path)).lower()
    if any(marker in value for marker in VAGUE_MARKERS):
      errors.append(f"vague_answer_not_allowed:{path}")

  if errors:
    raise RuntimeError("scenario_validation_failed:\n" + "\n".join(errors))


def _planning_payload() -> Dict[str, Any]:
  return {
    "contract_version": "planning_run_v1",
    "stage": "intake_complete",
    "status": "pending",
    "gpt_narrative": "Controlled scenario seeded as completed intake. Ready for backend planning.",
  }


def _numeric(value: Any) -> float:
  return round(max(0.0, _ARGS._extract_first_number(value) or 0.0), 6)


def _ratio(value: Any) -> float:
  return round(max(0.0, _ARGS._extract_ratio(value) or 0.0), 6)


def _apply_seeded_financial_extras(
  financials_json: Dict[str, Any],
  financials_spec: Dict[str, Any],
) -> Dict[str, Any]:
  out = dict(financials_json or {})
  for key in ("cogs_percent", "maintenance_capex_rate"):
    if key in financials_spec and _text(financials_spec.get(key)):
      out[key] = _ratio(financials_spec.get(key))
  for key in ("current_num_employees", "starting_ppe"):
    if key in financials_spec and _text(financials_spec.get(key)):
      out[key] = _numeric(financials_spec.get(key))
  if "cogs_total_year1" in financials_spec and _text(financials_spec.get("cogs_total_year1")):
    out["cogs_total_year1"] = _numeric(financials_spec.get("cogs_total_year1"))
  if "cash_strategy" in financials_spec:
    out["cash_strategy"] = _text(financials_spec.get("cash_strategy"))
  if "payroll_detail" in financials_spec:
    out["payroll_detail"] = _text(financials_spec.get("payroll_detail"))
  return out


def _build_seed_payload(spec: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  ops_json = _ARGS._build_operating_model(spec)
  milestones = spec.get("ops", {}).get("milestones")
  if isinstance(milestones, list) and milestones:
    ops_json["milestones"] = milestones
  market_json = _ARGS._build_target_market(spec, ops_json)
  people_json = _ARGS._build_people_json(spec)
  financials_json = _ARGS._build_financials_json(spec)
  financials_json = _apply_seeded_financial_extras(
    financials_json,
    spec.get("financials") if isinstance(spec.get("financials"), dict) else {},
  )
  shared_context = {"operating_model": ops_json}
  financials_year1_json = _YEAR1.assemble_financials_year1(shared_context, None)
  realism_memo_json = _ARGS._REALISM.generate_realism_memo_payload_safe(
    ops_json=ops_json,
    financials_json=financials_json,
  )
  planning_run_json = _planning_payload()
  return (
    ops_json,
    market_json,
    people_json,
    financials_json,
    financials_year1_json,
    realism_memo_json,
    planning_run_json,
  )


def _business_facts(spec: Dict[str, Any]) -> Dict[str, Any]:
  bootstrap = spec.get("bootstrap") if isinstance(spec.get("bootstrap"), dict) else {}
  return {
    "name": _text(bootstrap.get("business_name")),
    "address": _text(bootstrap.get("address")),
    "address_street": _text(bootstrap.get("address_street")),
    "address_city": _text(bootstrap.get("address_city")),
    "address_state": _text(bootstrap.get("address_state")),
    "address_zip": _text(bootstrap.get("address_zip")),
    "address_country": _text(bootstrap.get("address_country")),
    "start_date": _text(bootstrap.get("business_start_date")),
  }


def _seed_completed_draft(spec: Dict[str, Any], *, base_url: str) -> Tuple[str, str]:
  _ARGS._SCRIPTED._SHARED._load_env()
  session = _ARGS._DUAL._post_json(f"{base_url}/api/intake-consult/session", {})
  draft_id = _text(session.get("draft_id"))
  client_id = _text(session.get("client_id"))
  if not draft_id:
    raise RuntimeError(f"failed_to_create_backend_session:{session}")

  (
    ops_json,
    market_json,
    people_json,
    financials_json,
    financials_year1_json,
    realism_memo_json,
    planning_run_json,
  ) = _build_seed_payload(spec)

  message = {
    "role": "assistant",
    "content": "Controlled completed intake seeded from scenario JSON. No conversational intake was run.",
  }

  conn = _ARGS._SUBMISSION.get_mysql_connection()
  try:
    _ARGS._DRAFT.append_messages(
      conn,
      draft_id=draft_id,
      new_messages=[message],
      operating_model_json=ops_json,
      target_market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      realism_memo_json=realism_memo_json,
      planning_run_json=planning_run_json,
      pending_ops_milestone_json=[],
      active_focus="done",
      confirmations={"ops": True, "market": True, "people": True, "financials": True},
      business_facts=_business_facts(spec),
      flat_fields={
        "ops_finalize_proposed": 1,
        "market_finalize_proposed": 1,
        "people_finalize_proposed": 1,
        "financials_finalize_proposed": 1,
      },
      status="completed",
      completed=True,
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass
  return draft_id, client_id


def _run_persisted_e2e(*, draft_id: str, base_url: str, seed: str) -> int:
  cmd = [
    sys.executable,
    str(PERSISTED_RUNNER_PATH),
    "--draft-id",
    draft_id,
    "--base-url",
    base_url,
    "--seed",
    seed,
  ]
  completed = subprocess.run(cmd, cwd=str(ROOT))
  return int(completed.returncode or 0)


def main(argv: Optional[List[str]] = None) -> int:
  parser = argparse.ArgumentParser(
    description="Seed a completed intake_consult_drafts row from exhaustive CLI fields or an optional scenario JSON."
  )
  parser.add_argument("scenario_prompt", nargs="?", default="")
  parser.add_argument("--scenario-file", default="")
  parser.add_argument("--base-url", default="http://127.0.0.1:5050")
  parser.add_argument("--set", action="append", default=[], dest="overrides")
  parser.add_argument("--help-keys", action="store_true", help="Print every supported --set key pattern.")
  parser.add_argument("--dry-run", action="store_true", help="Validate and render payload summaries without touching SQL.")
  parser.add_argument("--run-system-run", action="store_true", help="After seeding, run Test Files/run_persisted_system_run.py against the seeded draft.")
  parser.add_argument("--seed", default="seeded-completed-intake")
  args = parser.parse_args(argv)

  if args.help_keys:
    print(_ARGS.KEY_HELP)
    print()
    print(EXTRA_KEY_HELP)
    return 0

  if not args.scenario_file and not args.overrides:
    raise RuntimeError("provide_exhaustive_--set_fields_or_--scenario-file")

  scenario_file = Path(args.scenario_file) if args.scenario_file else None
  spec = _load_spec(scenario_file, args.overrides, scenario_prompt=args.scenario_prompt)
  _validate_complete_spec(spec)
  payload = _build_seed_payload(spec)

  if args.dry_run:
    financials_year1_json = payload[4]
    print("scenario_validation=passed")
    print(f"business_name={_business_facts(spec).get('name')}")
    print(f"product_count={len(spec.get('ops', {}).get('products') or [])}")
    print(f"milestone_count={len(spec.get('ops', {}).get('milestones') or [])}")
    print(f"company_revenue_total_year1={financials_year1_json.get('company_revenue_total_year1')}")
    return 0

  draft_id, client_id = _seed_completed_draft(spec, base_url=args.base_url)
  print(f"seeded_draft_id={draft_id}")
  print(f"seeded_client_id={client_id}")
  print(
    "run_command="
    f"{sys.executable} \"{PERSISTED_RUNNER_PATH}\" --draft-id {draft_id} --base-url {args.base_url} --seed {args.seed}"
  )
  if args.run_system_run:
    return _run_persisted_e2e(draft_id=draft_id, base_url=args.base_url, seed=args.seed)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
