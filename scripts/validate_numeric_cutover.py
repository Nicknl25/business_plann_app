from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


PASS_SPECS: List[Tuple[str, str, str]] = [
  ("initial_restructure", "initial_restructure_pass_plan", "initial_restructure_pass_result"),
  ("realism_resolution", "realism_resolution_plan", "realism_resolution_result"),
  ("cash_strategy_review", "cash_strategy_second_pass_plan", "cash_strategy_second_pass_result"),
  ("final_stabilizer", "final_stabilizer_pass_plan", "final_stabilizer_pass_result"),
]


def _load_json(path: Path) -> Dict[str, Any]:
  raw = json.loads(path.read_text(encoding="utf-8"))
  if isinstance(raw, dict):
    if isinstance(raw.get("planning_run_json"), dict):
      return raw
    if isinstance(raw.get("row"), dict):
      return raw
  raise RuntimeError("Expected a JSON object containing either planning_run_json or row.")


def _planning_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
  if isinstance(doc.get("planning_run_json"), dict):
    return doc["planning_run_json"]
  row = doc.get("row") if isinstance(doc.get("row"), dict) else {}
  if isinstance(row.get("planning_run_json"), dict):
    return row["planning_run_json"]
  raise RuntimeError("Could not find planning_run_json payload.")


def _separate_feedback_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
  if isinstance(doc.get("numeric_solver_feedback_json"), dict):
    return doc["numeric_solver_feedback_json"]
  row = doc.get("row") if isinstance(doc.get("row"), dict) else {}
  if isinstance(row.get("numeric_solver_feedback_json"), dict):
    return row["numeric_solver_feedback_json"]
  return {}


def _contract(plan: Dict[str, Any]) -> Dict[str, Any]:
  return plan.get("numeric_solver_contract") if isinstance(plan.get("numeric_solver_contract"), dict) else {}


def _packages(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
  return [item for item in (plan.get("translated_action_packages") or []) if isinstance(item, dict)]


def _check_pass(name: str, plan: Dict[str, Any], result: Dict[str, Any]) -> List[str]:
  errors: List[str] = []
  contract = _contract(plan)
  active_issue_count = int(contract.get("active_issue_count") or 0)
  packages = _packages(plan)
  if active_issue_count <= 0:
    return errors

  if not packages:
    errors.append(f"{name}: active issues existed but translated_action_packages was empty.")

  for idx, package in enumerate(packages, start=1):
    allowed = [str(item).strip() for item in (package.get("solver_allowed_lever_ids") or []) if str(item).strip()]
    targets = [item for item in (package.get("quarter_target_metrics") or []) if isinstance(item, dict)]
    if not allowed:
      errors.append(f"{name}: package {idx} missing solver_allowed_lever_ids.")
    if not targets:
      errors.append(f"{name}: package {idx} missing quarter_target_metrics.")

  numeric_plan = result.get("numeric_execution_plan") if isinstance(result.get("numeric_execution_plan"), dict) else {}
  targeted_quarters = [int(item) for item in (numeric_plan.get("targeted_quarters") or []) if int(item) >= 1]
  allowed_levers = [str(item).strip() for item in (numeric_plan.get("allowed_lever_ids") or []) if str(item).strip()]
  if not targeted_quarters:
    errors.append(f"{name}: numeric_execution_plan.targeted_quarters was empty on an active-issue pass.")
  if not allowed_levers:
    errors.append(f"{name}: numeric_execution_plan.allowed_lever_ids was empty on an active-issue pass.")

  applied_update_count = int(result.get("applied_update_count") or 0)
  if applied_update_count <= 0:
    errors.append(f"{name}: pass completed with zero applied updates on an active-issue pass.")

  solver_result = result.get("numeric_solver_result") if isinstance(result.get("numeric_solver_result"), dict) else {}
  if "used_solver" in solver_result or "status" in solver_result:
    errors.append(f"{name}: legacy solver judgment keys still present in numeric_solver_result.")

  for attempt in [item for item in (solver_result.get("attempts") or []) if isinstance(item, dict)]:
    if "success" in attempt:
      errors.append(f"{name}: legacy attempt.success key still present in numeric_solver_result.attempts.")
      break

  return errors


def main(argv: List[str]) -> int:
  if len(argv) != 2:
    print("Usage: validate_numeric_cutover.py <json-file>")
    return 2

  path = Path(argv[1])
  doc = _load_json(path)
  planning = _planning_payload(doc)
  separate_feedback = _separate_feedback_payload(doc)

  errors: List[str] = []
  if not separate_feedback:
    errors.append("separate numeric_solver_feedback_json payload was missing.")

  for pass_name, plan_key, result_key in PASS_SPECS:
    plan = planning.get(plan_key) if isinstance(planning.get(plan_key), dict) else {}
    result = planning.get(result_key) if isinstance(planning.get(result_key), dict) else {}
    if not plan and not result:
      continue
    errors.extend(_check_pass(pass_name, plan, result))

  if errors:
    print("CUTOVER VALIDATION FAILED")
    for item in errors:
      print(f"- {item}")
    return 1

  print("CUTOVER VALIDATION PASSED")
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))
