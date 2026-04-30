"""Table-backed convergence contract policy.

Convergence rules should not live as scattered prose in intake_consult.py.
This module reads the SQL GPT contract lookup surface and returns the policy
payload that prompts, validators, and retry controllers can share.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.post_intake_mapping import (
  post_intake_contract_forecast_horizon_quarters,
  post_intake_gpt_contract_horizon_errors,
  post_intake_gpt_contract_prompt_field_spec,
)


_UNIFIED_CONVERGENCE_CONTRACT_NAME = "unified_convergence_decision"


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _field_for_path(fields: List[Dict[str, Any]], field_path: str) -> Dict[str, Any]:
  target = _clean_text(field_path)
  for row in fields:
    if _clean_text(row.get("field_path")) == target:
      return copy.deepcopy(row)
  return {}


def _contract_instruction_rows(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  seen: set[str] = set()
  for row in fields:
    instruction = _clean_text(row.get("prompt_required_instruction"))
    if not instruction:
      continue
    key = f"{_clean_text(row.get('field_path'))}|{instruction}"
    if key in seen:
      continue
    seen.add(key)
    rows.append(
      {
        "field_path": _clean_text(row.get("field_path")),
        "grid_name": _clean_text(row.get("grid_name")),
        "horizon_rule": _clean_text(row.get("horizon_rule")),
        "validation_kind": _clean_text(row.get("validation_kind")),
        "instruction": instruction,
      }
    )
  return rows


def build_unified_convergence_contract_policy() -> Dict[str, Any]:
  """Return the table-backed convergence policy payload used by post-intake."""
  spec = post_intake_gpt_contract_prompt_field_spec(_UNIFIED_CONVERGENCE_CONTRACT_NAME)
  forecast_quarters = post_intake_contract_forecast_horizon_quarters(
    contract_name=_UNIFIED_CONVERGENCE_CONTRACT_NAME,
  )
  fields = [
    copy.deepcopy(item)
    for item in (spec.get("fields") or [])
    if isinstance(item, dict)
  ]
  target_grid_rule = _field_for_path(fields, "targets_by_quarter")
  repair_cell_rule = _field_for_path(fields, "model_input_repair_cells")
  instruction_rows = _contract_instruction_rows(fields)
  return {
    "contract_name": _UNIFIED_CONVERGENCE_CONTRACT_NAME,
    "source_of_truth": spec.get("source_of_truth") or "sql.post_intake_gpt_contract_lookup",
    "contract_table": spec.get("contract_table") or "post_intake_gpt_contract_lookup",
    "required_forecast_quarters": copy.deepcopy(forecast_quarters),
    "horizon_rules": copy.deepcopy(spec.get("horizon_rules") or []),
    "normalization_rules": copy.deepcopy(spec.get("normalization_rules") or []),
    "target_grid_rule": {
      "field_path": target_grid_rule.get("field_path") or "targets_by_quarter",
      "min_items": target_grid_rule.get("min_items"),
      "max_items": target_grid_rule.get("max_items"),
      "horizon_rule": target_grid_rule.get("horizon_rule"),
      "validation_kind": target_grid_rule.get("validation_kind"),
      "instruction": target_grid_rule.get("prompt_required_instruction"),
    },
    "model_input_repair_cell_rule": {
      "field_path": repair_cell_rule.get("field_path") or "model_input_repair_cells",
      "horizon_rule": repair_cell_rule.get("horizon_rule"),
      "validation_kind": repair_cell_rule.get("validation_kind"),
      "instruction": repair_cell_rule.get("prompt_required_instruction"),
    },
    "mapping_rule": {
      "owner": "python",
      "source_of_truth": "sql.post_intak_mapping_lookup",
      "rule": "GPT chooses levers/cells; Python derives and validates issue/target mapping from the SQL mapping lookup table.",
    },
    "contract_instruction_rows": instruction_rows,
    "constraints": [row["instruction"] for row in instruction_rows],
  }


def unified_convergence_contract_constraints(extra_constraints: Optional[List[Any]] = None) -> List[str]:
  """Return deduped convergence constraints sourced from the SQL contract table."""
  policy = build_unified_convergence_contract_policy()
  constraints: List[str] = []
  for item in policy.get("constraints") or []:
    text = _clean_text(item)
    if text:
      constraints.append(text)
  for item in extra_constraints or []:
    text = _clean_text(item)
    if text:
      constraints.append(text)
  return list(dict.fromkeys(constraints))


def validate_unified_convergence_contract_horizon(payload: Any) -> List[str]:
  """Validate convergence horizon via the SQL contract lookup table."""
  return list(
    post_intake_gpt_contract_horizon_errors(
      contract_name=_UNIFIED_CONVERGENCE_CONTRACT_NAME,
      payload=payload,
    )
    or []
  )
