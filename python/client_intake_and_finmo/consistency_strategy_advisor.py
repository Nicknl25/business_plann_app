from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_RETRYABLE_STATUS = {429, 502, 503, 504}
_LEGACY_LEVER_KEYS = {
  "required_lever_families",
  "forbidden_lever_families",
  "coordinated_lever_packages",
  "lever_family_plan",
  "allowed_levers",
  "effective_lever_families",
  "package_lever_families",
  "legacy_allowed_levers",
}


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _bool_env(name: str, default: bool) -> bool:
  _load_root_env()
  raw = str(os.getenv(name) or "").strip().lower()
  if not raw:
    return default
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  return default


def _in_test_context() -> bool:
  joined_argv = " ".join(str(arg or "") for arg in sys.argv).lower()
  return (
    "test_planning_engines.py" in joined_argv
    or "unittest" in joined_argv
    or "\\tests\\" in joined_argv
  )


def _require_openai_key() -> str:
  _load_root_env()
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _openai_model() -> str:
  _load_root_env()
  return (
    os.getenv("CONSISTENCY_GPT_STRATEGY_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-5.1"
  ).strip() or "gpt-5.1"


def _timeout_env_int(name: str, default: int) -> int:
  _load_root_env()
  raw = (os.getenv(name) or "").strip()
  if not raw:
    return default
  try:
    return max(15, int(raw))
  except Exception:
    return default


def _openai_timeout_seconds(kind: str = "default") -> int:
  if kind == "audit":
    return _timeout_env_int("CONSISTENCY_GPT_AUDIT_TIMEOUT_SECONDS", 45)
  if kind == "validation":
    return _timeout_env_int("CONSISTENCY_GPT_VALIDATION_TIMEOUT_SECONDS", 60)
  if kind == "strategy":
    return _timeout_env_int("CONSISTENCY_GPT_STRATEGY_TIMEOUT_SECONDS", 75)
  return _timeout_env_int("OPENAI_HTTP_TIMEOUT_SECONDS", 180)


def _strategy_layer_enabled() -> bool:
  if _in_test_context():
    return _bool_env("CONSISTENCY_GPT_STRATEGY_LAYER", False)
  _load_root_env()
  if not str(os.getenv("OPENAI_API_KEY") or "").strip():
    return False
  return True


def _format_openai_error(resp: requests.Response) -> str:
  if resp.status_code in _RETRYABLE_STATUS:
    return "We're having trouble reaching our AI service right now. Please try again in a minute."
  return f"OpenAI API error {resp.status_code}: {resp.text[:500]}"


def _post_openai(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: Optional[int] = None,
  max_attempts: int = 3,
) -> requests.Response:
  timeout = max(15, int(timeout_seconds or _openai_timeout_seconds()))
  attempts = max(1, int(max_attempts or 1))
  last_exc: Optional[Exception] = None
  for attempt in range(attempts):
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
      if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
        time.sleep(0.75 * (2**attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      if attempt >= attempts - 1:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      if attempt >= attempts - 1:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def _parse_json_response(data: Dict[str, Any]) -> Dict[str, Any]:
  for item in data.get("output") or []:
    if not isinstance(item, dict):
      continue
    for part in item.get("content") or []:
      if not isinstance(part, dict):
        continue
      parsed = part.get("parsed")
      if isinstance(parsed, dict):
        return parsed
      if part.get("type") != "output_text":
        continue
      raw = str(part.get("text") or "").strip()
      if not raw:
        continue
      try:
        parsed = json.loads(raw)
      except Exception:
        continue
      if isinstance(parsed, dict):
        return parsed
  return {}


def _sanitize_canonical_live_payload(value: Any) -> Any:
  if isinstance(value, dict):
    cleaned: Dict[str, Any] = {}
    for raw_key, raw_val in value.items():
      key = str(raw_key or "")
      if key in _LEGACY_LEVER_KEYS:
        continue
      if key == "active_levers":
        cleaned[key] = [
          str(item or "").strip()
          for item in (raw_val or [])
          if str(item or "").strip() and "::" in str(item or "").strip()
        ]
        continue
      cleaned[key] = _sanitize_canonical_live_payload(raw_val)
    return cleaned
  if isinstance(value, list):
    return [_sanitize_canonical_live_payload(item) for item in value]
  return value


def _catalog_allowed_levers(strategy_catalog: List[Dict[str, Any]]) -> Dict[str, List[str]]:
  catalog: Dict[str, List[str]] = {}
  for item in strategy_catalog:
    if not isinstance(item, dict):
      continue
    strategy_id = str(item.get("strategy_id") or "").strip()
    if not strategy_id:
      continue
    catalog[strategy_id] = [
      str(lever_id or "").strip()
      for lever_id in (item.get("allowed_model_input_levers") or [])
      if str(lever_id or "").strip()
    ]
  return catalog


def _valid_finmo_line_items(fixed_facts: Dict[str, Any]) -> List[str]:
  finmo_json = (fixed_facts.get("finmo_json") or {}) if isinstance(fixed_facts.get("finmo_json"), dict) else {}
  labels: List[str] = []
  for section_key in ("pl", "balance_sheet", "cash_flow"):
    rows = finmo_json.get(section_key) if isinstance(finmo_json.get(section_key), list) else []
    for row in rows:
      if not isinstance(row, dict):
        continue
      label = str(row.get("label") or "").strip()
      if label:
        labels.append(label)
  if labels:
    return sorted({label for label in labels if label})
  return [
    "Revenue",
    "Gross Profit",
    "EBITDA",
    "Net Income",
    "Cash",
    "Total Assets",
    "Total Liabilities & Equity",
  ]


def _normalize_quarter_span(item: Dict[str, Any]) -> tuple[int, int]:
  start = item.get("quarter_start")
  end = item.get("quarter_end")
  try:
    start_int = max(1, min(20, int(start)))
  except Exception:
    start_int = 1
  try:
    end_int = max(start_int, min(20, int(end)))
  except Exception:
    end_int = start_int
  return start_int, end_int


def _normalize_strategy_selection_contract(
  *,
  selection: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
) -> Dict[str, Any]:
  if not isinstance(selection, dict):
    return {}
  allowed_by_strategy = _catalog_allowed_levers(strategy_catalog)
  valid_strategy_ids = list(allowed_by_strategy.keys())
  selected_strategy_ids = [
    str(item or "").strip()
    for item in (selection.get("selected_strategy_ids") or [])
    if str(item or "").strip() in allowed_by_strategy
  ][:2]
  allowed_from_selection = sorted({
    lever_id
    for strategy_id in selected_strategy_ids
    for lever_id in allowed_by_strategy.get(strategy_id, [])
  })
  valid_levers = set(allowed_from_selection)
  normalized = dict(selection)
  normalized["selected_strategy_ids"] = selected_strategy_ids
  requested_allowed = [
    str(item or "").strip()
    for item in (selection.get("allowed_model_input_levers") or [])
    if str(item or "").strip() in valid_levers
  ]
  normalized["allowed_model_input_levers"] = requested_allowed or allowed_from_selection
  allowed_set = set(normalized["allowed_model_input_levers"])
  normalized["forbidden_model_input_levers"] = [
    str(item or "").strip()
    for item in (selection.get("forbidden_model_input_levers") or [])
    if str(item or "").strip() in valid_levers and str(item or "").strip() not in allowed_set
  ]
  normalized_plan: List[Dict[str, Any]] = []
  for raw_item in (selection.get("lever_adjustment_plan") or []):
    if not isinstance(raw_item, dict):
      continue
    lever_id = str(raw_item.get("lever_id") or "").strip()
    if lever_id not in allowed_set:
      continue
    start_int, end_int = _normalize_quarter_span(raw_item)
    normalized_plan.append(
      {
        **raw_item,
        "lever_id": lever_id,
        "quarter_start": start_int,
        "quarter_end": end_int,
      }
    )
  normalized["lever_adjustment_plan"] = normalized_plan
  normalized_groups: List[Dict[str, Any]] = []
  for raw_group in (selection.get("governed_period_groups") or []):
    if not isinstance(raw_group, dict):
      continue
    start_int, end_int = _normalize_quarter_span(raw_group)
    raw_granularity = str(raw_group.get("input_granularity") or "").strip().lower()
    input_granularity = raw_granularity if raw_granularity in {"grouped", "quarterly"} else "grouped"
    quarterly_expansion_levers = [
      str(item or "").strip()
      for item in (raw_group.get("quarterly_expansion_levers") or [])
      if str(item or "").strip() in allowed_set
    ]
    normalized_groups.append(
      {
        **raw_group,
        "quarter_start": start_int,
        "quarter_end": end_int,
        "input_granularity": input_granularity,
        "quarterly_expansion_levers": quarterly_expansion_levers,
      }
    )
  normalized["governed_period_groups"] = normalized_groups
  valid_line_items = set(_valid_finmo_line_items(fixed_facts))
  normalized_targets: List[Dict[str, Any]] = []
  for raw_target in (selection.get("controlled_output_targets") or []):
    if not isinstance(raw_target, dict):
      continue
    line_item = str(raw_target.get("line_item") or "").strip()
    if line_item not in valid_line_items:
      continue
    start_int, end_int = _normalize_quarter_span(raw_target)
    normalized_targets.append(
      {
        **raw_target,
        "line_item": line_item,
        "quarter_start": start_int,
        "quarter_end": end_int,
      }
    )
  normalized["controlled_output_targets"] = normalized_targets
  normalized["valid_strategy_ids"] = valid_strategy_ids
  return normalized


def _forecast_orchestration_schema(*, required: bool) -> Dict[str, Any]:
  schema: Dict[str, Any] = {
    "type": ["object", "null"] if not required else "object",
    "additionalProperties": False,
    "properties": {
      "orchestration_summary": {"type": ["string", "null"]},
      "quarter_policies": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "quarter_start": {"type": "integer", "minimum": 1, "maximum": 20},
            "quarter_end": {"type": "integer", "minimum": 1, "maximum": 20},
            "demand_posture": {"type": ["string", "null"]},
            "staffing_posture": {"type": ["string", "null"]},
            "cost_posture": {"type": ["string", "null"]},
            "growth_multiplier": {"type": ["number", "null"]},
            "convergence_multiplier": {"type": ["number", "null"]},
            "price_growth_bias": {"type": ["number", "null"]},
            "utilization_target_bias": {"type": ["number", "null"]},
            "marketing_ratio_bias": {"type": ["number", "null"]},
            "opex_ratio_bias": {"type": ["number", "null"]},
            "payroll_ratio_bias": {"type": ["number", "null"]},
            "capacity_release_multiplier": {"type": ["number", "null"]},
            "active_levers": {
              "type": ["array", "null"],
              "items": {"type": "string"},
            },
          },
          "required": [
            "quarter_start",
            "quarter_end",
            "demand_posture",
            "staffing_posture",
            "cost_posture",
            "growth_multiplier",
            "convergence_multiplier",
            "price_growth_bias",
            "utilization_target_bias",
            "marketing_ratio_bias",
            "opex_ratio_bias",
            "payroll_ratio_bias",
            "capacity_release_multiplier",
            "active_levers",
          ],
        },
      },
      "role_timing_overrides": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "role_title": {"type": "string"},
            "months_until_activate": {"type": ["number", "null"]},
          },
          "required": ["role_title", "months_until_activate"],
        },
      },
      "milestone_timing_overrides": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "description": {"type": "string"},
            "months_until_activate": {"type": ["number", "null"]},
            "target_quarter": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
            "activation_condition": {"type": ["string", "null"]},
          },
          "required": ["description", "months_until_activate", "target_quarter", "activation_condition"],
        },
      },
      "event_response": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "hire_capacity_multiplier": {"type": ["number", "null"]},
          "hire_growth_bonus_delta": {"type": ["number", "null"]},
          "marketing_growth_multiplier": {"type": ["number", "null"]},
          "milestone_capacity_multiplier": {"type": ["number", "null"]},
          "milestone_growth_multiplier": {"type": ["number", "null"]},
        },
        "required": [
          "hire_capacity_multiplier",
          "hire_growth_bonus_delta",
          "marketing_growth_multiplier",
          "milestone_capacity_multiplier",
          "milestone_growth_multiplier",
        ],
      },
    },
    "required": [
      "orchestration_summary",
      "quarter_policies",
      "role_timing_overrides",
      "milestone_timing_overrides",
      "event_response",
    ],
  }
  return schema


def _quarter_plan_schema(*, fields: Dict[str, Any], required_fields: List[str]) -> Dict[str, Any]:
  return {
    "type": "array",
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        **fields,
      },
      "required": ["quarter_start", "quarter_end"] + required_fields,
    },
  }


def _hiring_release_plan_schema() -> Dict[str, Any]:
  return {
    "type": "array",
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "role_scope": {"type": "string"},
        "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "months_until_activate": {"type": ["number", "null"]},
        "staffing_posture": {"type": ["string", "null"]},
        "capacity_effect": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
      },
      "required": [
        "role_scope",
        "quarter_start",
        "quarter_end",
        "months_until_activate",
        "staffing_posture",
        "capacity_effect",
        "rationale",
      ],
    },
  }


def _milestone_activation_plan_schema() -> Dict[str, Any]:
  return {
    "type": "array",
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "description": {"type": "string"},
        "target_quarter": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "activation_condition": {"type": ["string", "null"]},
        "capacity_multiplier": {"type": ["number", "null"]},
        "growth_multiplier": {"type": ["number", "null"]},
        "rationale": {"type": "string"},
      },
      "required": [
        "description",
        "target_quarter",
        "activation_condition",
        "capacity_multiplier",
        "growth_multiplier",
        "rationale",
      ],
    },
  }


def _schema() -> Dict[str, Any]:
  return {
    "name": "consistency_strategy_selection",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "primary_cause": {
          "type": "string",
          "enum": ["payroll-driven", "pricing-driven", "utilization-driven", "mixed"],
        },
        "secondary_causes": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 4,
        },
        "reason": {"type": "string"},
        "business_model_assessment": {"type": "string"},
        "severity_class": {
          "type": "string",
          "enum": ["mild", "moderate", "severe"],
        },
        "severity_reason": {"type": "string"},
        "minimum_package_strength": {
          "type": "string",
          "enum": ["light", "moderate", "strong"],
        },
        "viability_blueprint_summary": {"type": "string"},
        "scaling_model_summary": {"type": "string"},
        "allowed_model_input_levers": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 48,
        },
        "forbidden_model_input_levers": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 24,
        },
        "controller_directives": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "minimum_meaningful_levers": {"type": ["integer", "null"], "minimum": 1, "maximum": 6},
            "require_multi_lever_coordination": {"type": ["boolean", "null"]},
            "preserve_capacity_staffing_link": {"type": ["boolean", "null"]},
            "preserve_price_demand_link": {"type": ["boolean", "null"]},
            "preserve_marketing_demand_link": {"type": ["boolean", "null"]},
            "prefer_delay_over_delete": {"type": ["boolean", "null"]},
            "aggression_level": {"type": ["string", "null"], "enum": ["low", "moderate", "high", None]},
            "escalate_on_retry": {"type": ["boolean", "null"]},
            "minimum_package_count": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
          },
          "required": [
            "minimum_meaningful_levers",
            "require_multi_lever_coordination",
            "preserve_capacity_staffing_link",
            "preserve_price_demand_link",
            "preserve_marketing_demand_link",
            "prefer_delay_over_delete",
            "aggression_level",
            "escalate_on_retry",
            "minimum_package_count",
          ],
        },
        "governed_period_groups": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "objective": {"type": ["string", "null"]},
              "input_granularity": {"type": ["string", "null"], "enum": ["grouped", "quarterly", None]},
              "quarterly_expansion_levers": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "maxItems": 24,
              },
              "rationale": {"type": "string"},
            },
            "required": ["quarter_start", "quarter_end", "objective", "input_granularity", "quarterly_expansion_levers", "rationale"],
          },
          "maxItems": 8,
        },
        "lever_adjustment_plan": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lever_id": {"type": "string"},
              "direction": {"type": ["string", "null"], "enum": ["up", "down", "hold", None]},
              "intensity": {"type": ["string", "null"], "enum": ["light", "moderate", "strong", None]},
              "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "min_value": {"type": ["number", "null"]},
              "max_value": {"type": ["number", "null"]},
              "rationale": {"type": "string"},
            },
            "required": [
              "lever_id",
              "direction",
              "intensity",
              "quarter_start",
              "quarter_end",
              "min_value",
              "max_value",
              "rationale",
            ],
          },
          "maxItems": 64,
        },
        "controlled_output_targets": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "line_item": {"type": "string"},
              "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "min_value": {"type": ["number", "null"]},
              "max_value": {"type": ["number", "null"]},
              "rationale": {"type": "string"},
            },
            "required": ["line_item", "quarter_start", "quarter_end", "min_value", "max_value", "rationale"],
          },
          "maxItems": 20,
        },
        "target_margin_path": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "year1_min": {"type": ["number", "null"]},
            "year1_max": {"type": ["number", "null"]},
            "year2_min": {"type": ["number", "null"]},
            "year2_max": {"type": ["number", "null"]},
            "year3_min": {"type": ["number", "null"]},
            "year3_max": {"type": ["number", "null"]},
          },
          "required": ["year1_min", "year1_max", "year2_min", "year2_max", "year3_min", "year3_max"],
        },
        "target_posture": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "year1_ebitda_posture": {"type": ["string", "null"]},
            "year2_ebitda_posture": {"type": ["string", "null"]},
            "year3_ebitda_posture": {"type": ["string", "null"]},
            "staffing_posture": {"type": ["string", "null"]},
            "pricing_posture": {"type": ["string", "null"]},
            "demand_posture": {"type": ["string", "null"]},
            "cost_posture": {"type": ["string", "null"]},
          },
          "required": [
            "year1_ebitda_posture",
            "year2_ebitda_posture",
            "year3_ebitda_posture",
            "staffing_posture",
            "pricing_posture",
            "demand_posture",
            "cost_posture",
          ],
        },
        "capacity_release_plan": _quarter_plan_schema(
          fields={
            "capacity_posture": {"type": ["string", "null"]},
            "capacity_release_multiplier": {"type": ["number", "null"]},
            "trigger": {"type": ["string", "null"]},
            "rationale": {"type": "string"},
          },
          required_fields=["capacity_posture", "capacity_release_multiplier", "trigger", "rationale"],
        ),
        "hiring_release_plan": _hiring_release_plan_schema(),
        "demand_build_plan": _quarter_plan_schema(
          fields={
            "demand_posture": {"type": ["string", "null"]},
            "marketing_ratio_bias": {"type": ["number", "null"]},
            "growth_multiplier": {"type": ["number", "null"]},
            "rationale": {"type": "string"},
          },
          required_fields=["demand_posture", "marketing_ratio_bias", "growth_multiplier", "rationale"],
        ),
        "milestone_activation_plan": _milestone_activation_plan_schema(),
        "support_overhead_plan": _quarter_plan_schema(
          fields={
            "cost_posture": {"type": ["string", "null"]},
            "opex_ratio_bias": {"type": ["number", "null"]},
            "payroll_ratio_bias": {"type": ["number", "null"]},
            "rationale": {"type": "string"},
          },
          required_fields=["cost_posture", "opex_ratio_bias", "payroll_ratio_bias", "rationale"],
        ),
        "outer_year_margin_logic": {"type": "string"},
        "selected_strategy_ids": {
          "type": "array",
          "items": {"type": "string"},
          "minItems": 1,
          "maxItems": 2,
        },
        "expected_year1_ebitda_margin_min": {"type": ["number", "null"]},
        "expected_year1_ebitda_margin_max": {"type": ["number", "null"]},
      },
      "required": [
        "primary_cause",
        "secondary_causes",
        "reason",
        "business_model_assessment",
        "severity_class",
        "severity_reason",
        "minimum_package_strength",
        "viability_blueprint_summary",
        "scaling_model_summary",
        "allowed_model_input_levers",
        "forbidden_model_input_levers",
        "controller_directives",
        "governed_period_groups",
        "lever_adjustment_plan",
        "controlled_output_targets",
        "target_margin_path",
        "target_posture",
        "capacity_release_plan",
        "hiring_release_plan",
        "demand_build_plan",
        "milestone_activation_plan",
        "support_overhead_plan",
        "outer_year_margin_logic",
        "selected_strategy_ids",
        "expected_year1_ebitda_margin_min",
        "expected_year1_ebitda_margin_max",
      ],
    },
  }


def _translation_audit_schema() -> Dict[str, Any]:
  return {
    "name": "consistency_controller_translation_audit",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "captured_correctly": {"type": "boolean"},
        "audit_status": {"type": "string", "enum": ["accepted", "accepted_with_minor_notes", "rejected_translation"]},
        "missing_intents": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 12,
        },
        "distorted_intents": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 12,
        },
        "introduced_conflicts": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 12,
        },
        "required_corrections": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 12,
        },
        "replacement_forecast_orchestration": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "orchestration_summary": {"type": "string"},
            "quarter_policies": {
              "type": "array",
              "maxItems": 24,
              "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                  "quarter_start": {"type": "integer", "minimum": 1, "maximum": 20},
                  "quarter_end": {"type": "integer", "minimum": 1, "maximum": 20},
                  "demand_posture": {"type": "string"},
                  "staffing_posture": {"type": "string"},
                  "cost_posture": {"type": "string"},
                  "growth_multiplier": {"type": "number"},
                  "convergence_multiplier": {"type": "number"},
                  "price_growth_bias": {"type": "number"},
                  "utilization_target_bias": {"type": "number"},
                  "marketing_ratio_bias": {"type": "number"},
                  "opex_ratio_bias": {"type": "number"},
                  "payroll_ratio_bias": {"type": "number"},
                  "capacity_release_multiplier": {"type": "number"},
                  "active_levers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 12,
                  },
                },
                "required": [
                  "quarter_start",
                  "quarter_end",
                  "demand_posture",
                  "staffing_posture",
                  "cost_posture",
                  "growth_multiplier",
                  "convergence_multiplier",
                  "price_growth_bias",
                  "utilization_target_bias",
                  "marketing_ratio_bias",
                  "opex_ratio_bias",
                  "payroll_ratio_bias",
                  "capacity_release_multiplier",
                  "active_levers",
                ],
              },
            },
            "role_timing_overrides": {
              "type": "array",
              "maxItems": 40,
              "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                  "role_title": {"type": "string"},
                  "months_until_activate": {"type": "integer", "minimum": 0, "maximum": 240},
                },
                "required": ["role_title", "months_until_activate"],
              },
            },
            "milestone_timing_overrides": {
              "type": "array",
              "maxItems": 20,
              "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                  "description": {"type": "string"},
                  "months_until_activate": {"type": "integer", "minimum": 0, "maximum": 240},
                  "target_quarter": {"type": "integer", "minimum": 1, "maximum": 20},
                  "activation_condition": {"type": "string"},
                },
                "required": ["description", "months_until_activate", "target_quarter", "activation_condition"],
              },
            },
            "event_response": {
              "type": "object",
              "additionalProperties": False,
              "properties": {
                "hire_capacity_multiplier": {"type": "number"},
                "hire_growth_bonus_delta": {"type": "number"},
                "marketing_growth_multiplier": {"type": "number"},
                "milestone_capacity_multiplier": {"type": "number"},
                "milestone_growth_multiplier": {"type": "number"},
              },
              "required": [
                "hire_capacity_multiplier",
                "hire_growth_bonus_delta",
                "marketing_growth_multiplier",
                "milestone_capacity_multiplier",
                "milestone_growth_multiplier",
              ],
            },
          },
          "required": [
            "orchestration_summary",
            "quarter_policies",
            "role_timing_overrides",
            "milestone_timing_overrides",
            "event_response",
          ],
        },
        "notes": {"type": "string"},
      },
      "required": [
        "captured_correctly",
        "audit_status",
        "missing_intents",
        "distorted_intents",
        "introduced_conflicts",
        "required_corrections",
        "replacement_forecast_orchestration",
        "notes",
      ],
    },
  }


def _validation_schema() -> Dict[str, Any]:
  return {
    "name": "consistency_finmo_validation",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "validation_status": {
          "type": "string",
          "enum": ["accepted", "accepted_with_notes", "rejected"],
        },
        "believable": {"type": "boolean"},
        "viable_path": {"type": "boolean"},
        "output_matches_intent": {"type": "boolean"},
        "issues": {
          "type": "array",
          "items": {"type": "string"},
        },
        "required_adjustments": {
          "type": "array",
          "items": {"type": "string"},
        },
        "notes": {"type": "string"},
      },
      "required": [
        "validation_status",
        "believable",
        "viable_path",
        "output_matches_intent",
        "issues",
        "required_adjustments",
        "notes",
      ],
    },
  }


def advise_consistency_strategy_selection(
  *,
  baseline_summary: Dict[str, Any],
  fixed_facts: Dict[str, Any],
  viability_mode: bool,
  diagnosis: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  solver_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  if not _strategy_layer_enabled():
    return {}
  try:
    api_key = _require_openai_key()
  except Exception:
    return {}

  catalog_payload = []
  for item in strategy_catalog:
    if not isinstance(item, dict):
      continue
    catalog_payload.append(
      {
        "strategy_id": str(item.get("strategy_id") or "").strip(),
        "strategy_name": str(item.get("strategy_name") or "").strip(),
        "archetype": str(item.get("archetype") or "").strip(),
        "allowed_model_input_levers": list(item.get("allowed_model_input_levers") or []),
        "allowed_model_input_lever_details": _sanitize_canonical_live_payload(item.get("allowed_model_input_lever_details") or []),
        "dominant_tradeoff": str(item.get("dominant_tradeoff") or "").strip(),
      }
    )
  if not catalog_payload:
    return {}

  schema = _schema()
  base_user_payload = {
    "baseline_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "fixed_facts": _sanitize_canonical_live_payload(fixed_facts or {}),
    "model_input_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("model_input_json") or {}),
    "finmo_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("finmo_json") or {}),
    "viability_mode": bool(viability_mode),
    "deterministic_diagnosis": _sanitize_canonical_live_payload(diagnosis or {}),
    "strategy_catalog": catalog_payload,
  }
  if isinstance(solver_feedback, dict) and solver_feedback:
    base_user_payload["solver_feedback"] = _sanitize_canonical_live_payload(solver_feedback)

  system_prompts = [
    (
      "You are the governor for a business-plan realism and repair engine.\n"
      "\n"
      "Mission:\n"
      "Build a believable viable business over 20 quarters, not a cosmetic improvement and not a fake spreadsheet win.\n"
      "Choose the best 1 or 2 strategy ids from the provided bounded strategy catalog.\n"
      "Do not invent new strategy ids.\n"
      "\n"
      "Thinking Standard:\n"
      "Reason like a serious operator and investor reviewing a flawed plan.\n"
      "Use the full business picture: persisted intake facts, consultant outputs, baseline_summary, deterministic_diagnosis, model_input_view, finmo_view, solver_feedback, and your own real-world knowledge of how this business type should actually operate.\n"
      "The persisted SQL state is the client's stated plan and starting point, not the truth. Challenge unrealistic pricing, compensation, staffing, utilization, growth, margin, and timing assumptions when they are not believable.\n"
      "If the baseline is implausibly weak, stabilize it. If it is implausibly strong, normalize it. Do not simply preserve client optimism.\n"
      "Avoid long negative paths. A repaired business may still have early pressure, but multi-year flat or worsening losses are usually unacceptable unless the business facts truly force that outcome.\n"
      "If the business is structurally unprofitable, unrealistic, or failing to converge toward a believable steady state, you must prescribe a coordinated multi-lever restructuring that creates a plausible path to viability.\n"
      "In those cases, do not return incremental, cosmetic, timid, or overly conservative adjustments that leave the business failing.\n"
      "A valid repair must materially change the operating structure when needed, coordinate multiple levers across revenue, staffing, utilization, and cost, and produce a believable path toward breakeven or acceptable margins within a reasonable timeframe for the business type and stage.\n"
      "\n"
      "Shared Language Contract:\n"
      "You may only prescribe controllable levers using exact Model Inputs workbook lever ids from strategy_catalog.allowed_model_input_levers.\n"
      "Use strategy_catalog.allowed_model_input_lever_details to understand what each workbook lever means, whether it is a ratio or direct input, which full quarters it may control, and whether it belongs to revenue, expenses, balance sheet, or schedules.\n"
      "Do not invent lever names, abstractions, synonyms, or old solver-family vocabulary.\n"
      "When prescribing a lever, speak in the exact workbook language shown in model_input_view. Controller is not allowed to infer synonyms later.\n"
      "forbidden_model_input_levers are workbook levers that should stay mostly untouched for this case.\n"
      "\n"
      "Revenue Reasoning:\n"
      "Read the revenue section carefully. Revenue levers are scoped by line of business and product, not just by generic driver name.\n"
      "Reason explicitly about LOB, product, capacity, unit price, and utilization together.\n"
      "Do not change revenue drivers in a way that breaks business logic. Price, utilization, capacity, demand pacing, and staffing support must still fit together.\n"
      "If child products exist, preserve child-first reasoning. Parent behavior should emerge from children rather than replacing them.\n"
      "\n"
      "Cost and Compensation Reasoning:\n"
      "Treat payroll, founder pay, leadership compensation, planned hires, marketing, COGS, G&A, lease, interest, depreciation, and taxes as business design choices, not sacred inputs.\n"
      "If compensation is economically unrealistic, you may cut it, defer it, or phase it back in later.\n"
      "If inferred or planned roles are not supportable, delay them, reduce them, or reshape the operating model so the staffing plan becomes believable.\n"
      "If you defer staffing or compensation, the rest of the business must stay coherent: capacity, utilization, growth pacing, support overhead, and demand build must still make sense.\n"
      "\n"
      "Time Horizon and Grouping:\n"
      "You are governing Quarter 1 through Quarter 20.\n"
      "Use exact timing and mostly grouped quarter phases, not twenty fully independent quarter decisions by default.\n"
      "Use finer quarter-level control only when the business logic truly requires it.\n"
      "Each governed_period_group must declare input_granularity as grouped or quarterly.\n"
      "If a group is grouped, controller must keep that phase tied unless you explicitly authorize specific quarterly_expansion_levers for that group.\n"
      "Do not assume controller will decide where to expand or break phases apart. If quarter-level freedom is needed, you must authorize it explicitly.\n"
      "You must decide when changes start, when they stop, when capacity expands, when roles release, when demand builds, when milestones activate, and when support overhead steps up because scale is real.\n"
      "\n"
      "Bands and Targets:\n"
      "Use exact timing but mostly bounded ranges for controllable inputs. Do not pin exact values unless something truly must be fixed.\n"
      "Controller needs room to solve numerically inside your bands. If you pin everything exactly, Solver becomes ineffective and feasibility collapses.\n"
      "controlled_output_targets should usually be bands by quarter group or year phase, not brittle point targets.\n"
      "Use Financial Model QTR line items like Revenue, EBITDA, Gross Profit, Net Income, Cash, Total Assets, or Total Liabilities & Equity.\n"
      "Your target_margin_path for Years 1, 2, and 3 must be believable for this business type and stage and plausibly reachable by the lever package you return.\n"
      "\n"
      "Controller Handoff:\n"
      "Controller is an execution layer, not a co-strategist.\n"
      "Your output must be specific enough that controller only has to translate your workbook lever plan into Excel Solver changing-cell instructions and stay within your bands.\n"
      "Do not rely on hidden controller heuristics or global envelope overrides. You are the source of business logic, timing, and bounds.\n"
      "Controller directives tell the numeric layer how strictly to preserve causal links like staffing-to-capacity, price-to-demand, and marketing-to-demand.\n"
      "\n"
      "Required Output Content:\n"
      "Return a full viability blueprint, not just strategy ids.\n"
      "You must explain the business_model_assessment, secondary_causes, allowed_model_input_levers, forbidden_model_input_levers, controller_directives, governed_period_groups, lever_adjustment_plan, controlled_output_targets, target_posture, viability_blueprint_summary, scaling_model_summary, target_margin_path, capacity_release_plan, hiring_release_plan, demand_build_plan, milestone_activation_plan, support_overhead_plan, outer_year_margin_logic, and expected_year1 EBITDA range.\n"
      "Do not rely on controller to invent quarter logic later. Quarter logic must be fully expressed through governed_period_groups, lever_adjustment_plan, controlled_output_targets, and the release/build plans.\n"
      "\n"
      "Severity and Retry:\n"
      "Classify case severity as mild, moderate, or severe and explain why in severity_reason.\n"
      "Set minimum_package_strength to light, moderate, or strong.\n"
      "Set controller_directives.aggression_level to low, moderate, or high based on how broken the business is.\n"
      "If the case is badly broken, set escalate_on_retry=true and require a higher minimum_meaningful_levers and minimum_package_count.\n"
      "If deterministic_diagnosis includes severity_class=severe, you must return a severe blueprint: aggression_level=high, escalate_on_retry=true, minimum_package_strength=strong, minimum_meaningful_levers>=4, minimum_package_count>=2, and materially different quarter groups or lever bands.\n"
      "When severity_class is moderate or severe, you must use at least one revenue-side lever, at least one cost-side or staffing lever, include both early-phase and outer-year changes, and produce a non-flat trajectory.\n"
      "Do not return single-lever or weak adjustments in moderate or severe cases unless the business facts make that the only believable path.\n"
      "For severe cases, do not return a polite or modest plan. Return a strong but realistic multi-lever restructuring path.\n"
      "For severe cases, lever_adjustment_plan must cover at least four meaningful workbook levers, include at least one revenue-side lever and at least one cost-side lever, and include both an early-phase action and an outer-year action.\n"
      "When a business is structurally broken, you are expected to make decisive but believable moves, not small adjustments that preserve failure.\n"
      "Use solver_feedback carefully. On retry, do not just rename the same weak strategy. Change the lever package, bounds, timing, or target path enough to materially improve solvability.\n"
      "If solver_feedback.escalation_required is true, the prior attempts still produced all-negative degrading five-year paths. In that case, do not repeat the same strategy story. Materially strengthen the operating plan, growth architecture, and target posture.\n"
      "\n"
      "Believability Rules:\n"
      "Business type and business stage matter materially when deciding what is realistic.\n"
      "If EBITDA is weak, provide a realistic Year-1 expected EBITDA margin range for a repaired but still believable Year 1. Do not force mature margins too early.\n"
      "If a business is badly broken, do not rely on a single lever unless a single-lever repair is truly believable.\n"
      "Choose strategies that keep the business believable, preserve the original plan where possible, and avoid nonsense even when Solver could technically force the numbers.\n"
      "Return JSON only."
    ),
    (
      "You are rescuing a failed strategy-selection attempt for a business-plan realism and repair engine.\n"
      "The previous strategy choice did not produce a viable repair, or selection output was missing.\n"
      "You must still choose 1 or 2 strategy ids from the provided catalog.\n"
      "Do not return an empty selection.\n"
      "Use solver_feedback to avoid repeating the same failed strategy story.\n"
      "Pick a different, still-believable operating approach if the previous one missed.\n"
      "Return JSON only."
    ),
    (
      "You must return a valid strategy selection now.\n"
      "Select the best 1 or 2 strategy ids from the catalog and provide conservative overrides.\n"
      "Do not leave selected_strategy_ids empty.\n"
      "Prefer believable repair over perfect optimization.\n"
      "Return JSON only."
    ),
  ]

  last_error: Optional[str] = None
  for attempt_index, system_prompt in enumerate(system_prompts, start=1):
    payload = {
      "model": _openai_model(),
      "input": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(base_user_payload, ensure_ascii=False)},
      ],
      "text": {
        "format": {
          "type": "json_schema",
          "name": schema["name"],
          "schema": schema["schema"],
          "strict": True,
        }
      },
    }
    url = "https://api.openai.com/v1/responses"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
      resp = _post_openai(
        url=url,
        headers=headers,
        payload=payload,
        timeout_seconds=_openai_timeout_seconds("strategy"),
        max_attempts=2,
      )
      if resp.status_code >= 400:
        last_error = _format_openai_error(resp)
        continue
      parsed = _parse_json_response(resp.json())
    except Exception as exc:
      last_error = str(exc)
      continue
    if not isinstance(parsed, dict):
      last_error = "non_dict_response"
      continue
    parsed = _normalize_strategy_selection_contract(
      selection=parsed,
      strategy_catalog=strategy_catalog,
      fixed_facts=fixed_facts or {},
    )
    selected_ids = parsed.get("selected_strategy_ids")
    if isinstance(selected_ids, list) and any(str(item or "").strip() for item in selected_ids):
      parsed["advisor_attempt_count"] = attempt_index
      return parsed
    last_error = "missing_selected_strategy_ids"
  return {
    "error": "strategy_advisor_no_selection",
    "error_detail": str(last_error or "unknown"),
  }


def audit_consistency_controller_translation(
  *,
  strategy_selection: Dict[str, Any],
  translated_contract: Dict[str, Any],
  translated_modified_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  if not _strategy_layer_enabled():
    return {}
  try:
    api_key = _require_openai_key()
  except Exception:
    return {}
  payload = {
    "strategy_selection": _sanitize_canonical_live_payload(strategy_selection or {}),
    "translated_contract": _sanitize_canonical_live_payload(translated_contract or {}),
    "translated_modified_state": _sanitize_canonical_live_payload(translated_modified_state or {}),
  }
  schema = _translation_audit_schema()
  request_payload = {
    "model": _openai_model(),
    "input": [
      {
        "role": "system",
        "content": (
          "You are auditing a controller translation for a business-plan realism engine.\n"
          "Your only job is to decide whether the persisted controller translation preserved GPT intent.\n"
          "Do not redesign the business. Do not create a new strategy. Only audit translation fidelity.\n"
          "Check whether required directions, timing, growth architecture, hiring release, milestone activation, support-overhead logic, and forbidden moves were preserved.\n"
          "Reject the translation if it introduces opposite-direction conflicts, loses staged hiring or milestone intent, or produces quarter logic that clearly contradicts the original plan.\n"
          "If you reject the translation, you must also return replacement_forecast_orchestration using the controller/forecast language.\n"
          "That replacement must directly encode the corrected quarter_policies, role_timing_overrides, milestone_timing_overrides, and event_response needed to preserve the original GPT intent.\n"
          "If the translation is acceptable, return an empty but valid replacement_forecast_orchestration object with empty arrays and neutral event_response.\n"
          "Return JSON only."
        ),
      },
      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema["name"],
        "schema": schema["schema"],
        "strict": True,
      }
    },
  }
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  try:
    resp = _post_openai(
      url=url,
      headers=headers,
      payload=request_payload,
      timeout_seconds=_openai_timeout_seconds("audit"),
      max_attempts=1,
    )
    if resp.status_code >= 400:
      return {"error": _format_openai_error(resp)}
    parsed = _parse_json_response(resp.json())
  except Exception as exc:
    return {"error": str(exc)}
  return parsed if isinstance(parsed, dict) else {}


def validate_consistency_finmo_result(
  *,
  validation_request: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  fixed_facts: Optional[Dict[str, Any]] = None,
  strategy_selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  if not _strategy_layer_enabled():
    return {}
  try:
    api_key = _require_openai_key()
  except Exception:
    return {}

  payload = {
    "validation_request": _sanitize_canonical_live_payload(validation_request or {}),
    "model_input_view": _sanitize_canonical_live_payload(model_input_json or {}),
    "finmo_view": _sanitize_canonical_live_payload(finmo_json or {}),
    "fixed_facts": _sanitize_canonical_live_payload(fixed_facts or {}),
    "strategy_selection": _sanitize_canonical_live_payload(strategy_selection or {}),
  }
  schema = _validation_schema()
  request_payload = {
    "model": _openai_model(),
    "input": [
      {
        "role": "system",
        "content": (
          "You are validating a persisted Finmo result for a business-plan realism and repair engine.\n"
          "Your job is to judge whether the latest persisted Model Inputs and Financial Model QTR outputs match the intended governed business path and are believable.\n"
          "Use the full business picture: fixed_facts, strategy_selection, validation_request, model_input_view, finmo_view, and your own real-world knowledge of how this business type should actually operate.\n"
          "Do not invent new levers or redesign the business from scratch. Validate the result that was actually produced.\n"
          "A passing result must be believable, materially aligned with the requested timing and output intent, and plausibly converge toward a viable operating state.\n"
          "Reject results that are still structurally weak, unrealistic, flatly failing, or materially inconsistent with the intended lever timing and business logic.\n"
          "Do not accept a result just because the spreadsheet improves. It must be believable and viable enough for the business type and stage.\n"
          "Return JSON only."
        ),
      },
      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema["name"],
        "schema": schema["schema"],
        "strict": True,
      }
    },
  }
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  try:
    resp = _post_openai(
      url=url,
      headers=headers,
      payload=request_payload,
      timeout_seconds=_openai_timeout_seconds("validation"),
      max_attempts=1,
    )
    if resp.status_code >= 400:
      return {"error": _format_openai_error(resp)}
    parsed = _parse_json_response(resp.json())
  except Exception as exc:
    return {"error": str(exc)}
  return parsed if isinstance(parsed, dict) else {}
