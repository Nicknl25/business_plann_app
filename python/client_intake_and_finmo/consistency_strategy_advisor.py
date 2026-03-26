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


def _openai_timeout_seconds() -> int:
  _load_root_env()
  raw = (os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS") or "").strip()
  if raw:
    try:
      return max(30, int(raw))
    except Exception:
      return 180
  return 180


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


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  last_exc: Optional[Exception] = None
  for attempt in range(3):
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
      if resp.status_code in _RETRYABLE_STATUS and attempt < 2:
        time.sleep(0.75 * (2**attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      if attempt >= 2:
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
          },
          "required": ["description", "months_until_activate"],
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
        "required_lever_families": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 8,
        },
        "forbidden_lever_families": {
          "type": "array",
          "items": {"type": "string"},
          "maxItems": 8,
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
        "coordinated_lever_packages": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "quarter_start": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "quarter_end": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
              "levers": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
              },
              "expected_effects": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
              },
              "minimum_strength": {"type": ["string", "null"], "enum": ["light", "moderate", "strong", None]},
              "rationale": {"type": "string"},
            },
            "required": ["quarter_start", "quarter_end", "levers", "expected_effects", "minimum_strength", "rationale"],
          },
          "maxItems": 8,
        },
        "selected_strategy_ids": {
          "type": "array",
          "items": {"type": "string"},
          "minItems": 1,
          "maxItems": 2,
        },
        "strategy_overrides": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "strategy_id": {"type": "string"},
              "allowed_levers": {
                "type": ["array", "null"],
                "items": {"type": "string"},
              },
              "constraints": {
                "type": ["object", "null"],
                "additionalProperties": {
                  "type": ["number", "boolean", "null"],
                },
              },
              "forecast_orchestration": _forecast_orchestration_schema(required=False),
            },
            "required": ["strategy_id", "allowed_levers", "constraints", "forecast_orchestration"],
          },
        },
        "global_overrides": {
          "type": ["object", "null"],
          "additionalProperties": False,
          "properties": {
            "price_min_ratio": {"type": ["number", "null"]},
            "price_max_ratio": {"type": ["number", "null"]},
            "util_min": {"type": ["number", "null"]},
            "util_max": {"type": ["number", "null"]},
            "marketing_up_cap_ratio": {"type": ["number", "null"]},
            "marketing_down_cap_ratio": {"type": ["number", "null"]},
            "other_opex_down_cap_ratio": {"type": ["number", "null"]},
            "other_opex_up_cap_ratio": {"type": ["number", "null"]},
            "cogs_ratio_min": {"type": ["number", "null"]},
            "cogs_ratio_max": {"type": ["number", "null"]},
            "marketing_role": {"type": ["string", "null"]},
            "opex_flexibility": {"type": ["string", "null"]},
          },
          "required": [
            "price_min_ratio",
            "price_max_ratio",
            "util_min",
            "util_max",
            "marketing_up_cap_ratio",
            "marketing_down_cap_ratio",
            "other_opex_down_cap_ratio",
            "other_opex_up_cap_ratio",
            "cogs_ratio_min",
            "cogs_ratio_max",
            "marketing_role",
            "opex_flexibility",
          ],
        },
        "baseline_forecast_orchestration": _forecast_orchestration_schema(required=True),
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
        "required_lever_families",
        "forbidden_lever_families",
        "controller_directives",
        "target_margin_path",
        "target_posture",
        "coordinated_lever_packages",
        "selected_strategy_ids",
        "strategy_overrides",
        "global_overrides",
        "baseline_forecast_orchestration",
        "expected_year1_ebitda_margin_min",
        "expected_year1_ebitda_margin_max",
      ],
    },
  }


def advise_consistency_strategy_selection(
  *,
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_forecast_bundle: Optional[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
  viability_mode: bool,
  diagnosis: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  orchestration_context: Optional[Dict[str, Any]] = None,
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
        "allowed_levers": list(item.get("allowed_levers") or []),
        "relationship_rules": list(item.get("relationship_rules") or []),
        "constraints": dict(item.get("constraints") or {}),
        "dominant_tradeoff": str(item.get("dominant_tradeoff") or "").strip(),
      }
    )
  if not catalog_payload:
    return {}

  schema = _schema()
  base_user_payload = {
    "baseline_summary": baseline_summary or {},
    "constraint_engine_state": constraint_engine_state or {},
    "baseline_forecast": baseline_forecast_bundle or {},
    "fixed_facts": fixed_facts or {},
    "orchestration_context": orchestration_context or {},
    "viability_mode": bool(viability_mode),
    "deterministic_diagnosis": diagnosis or {},
    "strategy_catalog": catalog_payload,
  }
  if isinstance(solver_feedback, dict) and solver_feedback:
    base_user_payload["solver_feedback"] = solver_feedback

  system_prompts = [
    (
      "You are the strategy layer for a business-plan realism and repair engine.\n"
      "Your job is to choose the 1 or 2 best strategies from the provided bounded strategy catalog.\n"
      "Do not invent new strategy ids.\n"
      "Use the baseline business, constraint state, and forecast to determine the primary cause of unrealistic performance or non-viability.\n"
      "You are governing reality from Quarter 1 through Quarter 20, not only rescuing downside cases.\n"
      "If baseline economics are implausibly weak, stabilize them. If they are implausibly strong, normalize them.\n"
      "Return a viability blueprint, not just strategy ids.\n"
      "You must explain the business model assessment, secondary causes, required lever families, forbidden lever families, coordinated lever packages, controller directives, and target posture.\n"
      "You must classify case severity as mild, moderate, or severe and explain why in severity_reason.\n"
      "You must also set minimum_package_strength to light, moderate, or strong.\n"
      "You must also return a numeric target_margin_path for Years 1, 2, and 3 that reflects a believable path to viability for this business type and stage.\n"
      "Your target_margin_path must be plausibly reachable by the lever package you return. Do not state a Year 1-3 path that your own package cannot support.\n"
      "Required lever families are the levers that must move together for this business to become believable.\n"
      "Forbidden lever families are levers that should stay mostly untouched for this case.\n"
      "Controller directives tell the numeric translation layer how strictly to preserve causal links like staffing-to-capacity, price-to-demand, and marketing-to-demand.\n"
      "Set controller_directives.aggression_level to low, moderate, or high based on how broken the business is.\n"
      "If the case is badly broken, set escalate_on_retry=true and require a higher minimum_meaningful_levers / minimum_package_count.\n"
      "If deterministic_diagnosis includes severity_class=severe, you must return a severe blueprint: aggression_level=high, escalate_on_retry=true, minimum_package_strength=strong, minimum_meaningful_levers>=4, minimum_package_count>=2, and at least one strong coordinated package.\n"
      "For severe cases, do not return a polite or modest plan. Return a strong but realistic multi-lever restructuring path.\n"
      "Target posture should describe what Year 1, Year 2, and Year 3 should broadly feel like for EBITDA and the operating model.\n"
      "Coordinated lever packages must include expected_effects and minimum_strength, not just lever names.\n"
      "For severe cases, coordinated packages must move multiple business families together and should usually include pricing, cost structure, staffing/capacity timing, and demand/utilization pacing unless a family is clearly not relevant.\n"
      "Choose strategies that keep the business believable, preserve the original plan where possible, and avoid extreme moves.\n"
      "For each selected strategy, you may tighten or widen the provided constraints and allowed levers, but stay believable.\n"
      "Use strategy_overrides to feed solver the right bounds for this business shape.\n"
      "Use global_overrides when the whole business realism envelope should shift before solving.\n"
      "You must also orchestrate the full 20-quarter forecast path.\n"
      "Return baseline_forecast_orchestration for the current plan and, where needed, strategy-specific forecast_orchestration in strategy_overrides.\n"
      "These quarter policies must govern the whole business, not just payroll: demand, pricing, utilization, staffing, marketing, opex, cogs, capacity, and timed events.\n"
      "Preserve child-first behavior whenever child products exist; parent-level behavior should emerge from children, not replace them.\n"
      "If roles or milestones are not supposed to activate until later, delay them explicitly in role_timing_overrides or milestone_timing_overrides.\n"
      "When staffing is delayed, supportable capacity and growth should stay tighter until the role activates.\n"
      "Use both the persisted business data and your broader knowledge of what similar businesses typically look like.\n"
      "The SQL state is the starting plan, not the truth, so recognize when persisted revenue, margins, staffing efficiency, or growth are implausible.\n"
      "Business type and business stage matter materially when deciding what is realistic.\n"
      "Constraint values should remain bounded and realistic. Examples include price_up_cap_ratio, util_down_cap_ratio, units_min_ratio,\n"
      "marketing_up_cap_ratio, marketing_min_ratio, marketing_max_ratio, payroll_up_max_ratio, payroll_down_max_ratio,\n"
      "hire_delay_max_months_total, hire_advance_max_months_total, utilization_min_ratio, utilization_max_ratio,\n"
      "other_opex_down_cap_ratio, other_opex_up_cap_ratio, cogs_down_cap_ratio, cogs_up_cap_ratio, prefer_growth_units.\n"
      "Global overrides can adjust price_min_ratio, price_max_ratio, util_min, util_max, marketing and opex cap ratios, cogs ratio range,\n"
      "and commercial posture like marketing_role or opex_flexibility.\n"
      "If EBITDA is weak, provide a realistic Year-1 expected EBITDA margin range that reflects what a repaired but still believable Year 1 should look like.\n"
      "Do not force mature margins. For difficult or early-stage businesses, a slightly negative or near-break-even Year 1 can still be reasonable.\n"
      "If a business is badly broken, do not rely on a single lever. Return a coordinated multi-lever package unless a single-lever repair is truly believable.\n"
      "Use solver_feedback carefully. On retry, do not just rename the same weak strategy. Change the lever package, bounds, timing, or target path enough to materially improve solvability.\n"
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
      resp = _post_openai(url=url, headers=headers, payload=payload)
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
    selected_ids = parsed.get("selected_strategy_ids")
    if isinstance(selected_ids, list) and any(str(item or "").strip() for item in selected_ids):
      parsed["advisor_attempt_count"] = attempt_index
      return parsed
    last_error = "missing_selected_strategy_ids"
  return {
    "error": "strategy_advisor_no_selection",
    "error_detail": str(last_error or "unknown"),
  }
