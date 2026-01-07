from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import requests

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _require_openai_key() -> str:
  _load_root_env()
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _openai_model() -> str:
  _load_root_env()
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _openai_timeout_seconds() -> int:
  _load_root_env()
  raw = (os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS") or "").strip()
  if raw:
    try:
      return max(30, int(raw))
    except Exception:
      return 180
  return 180


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  last_exc: Optional[Exception] = None
  for attempt in range(3):
    try:
      return requests.post(url, headers=headers, json=payload, timeout=timeout)
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


def _json_default(obj: Any) -> Any:
  """
  Make context JSON-serializable (MySQL connector returns Decimals).
  """
  if isinstance(obj, Decimal):
    try:
      return float(obj)
    except Exception:
      return str(obj)
  if isinstance(obj, (datetime, date)):
    try:
      return obj.isoformat()
    except Exception:
      return str(obj)
  return str(obj)


def _value_schema_by_consult_field(*, consult_type: str) -> Dict[str, Any]:
  consult_type_norm = str(consult_type or "").strip().lower()
  if consult_type_norm == "unified":
    # Patch keys are scoped (group.field). This mapping is used for deterministic
    # type checking of value_json payloads.
    schemas: Dict[str, Any] = {}

    def add(group: str, field: str, schema: Dict[str, Any]) -> None:
      schemas[f"{group}.{field}"] = schema

    # business facts (stored on the draft)
    add("business", "name", {"type": "string"})
    add("business", "address", {"type": "string"})
    add("business", "start_date", {"type": "string"})

    # ops
    for k, v in _value_schema_by_consult_field(consult_type="ops").items():
      add("ops", k, v)

    # market
    for k, v in _value_schema_by_consult_field(consult_type="target_market").items():
      add("market", k, v)

    # people
    for k, v in _value_schema_by_consult_field(consult_type="people").items():
      add("people", k, v)

    # financials
    for k, v in _value_schema_by_consult_field(consult_type="financials").items():
      add("financials", k, v)

    # model cards (stored on the unified consult draft)
    add("pricing", "unit_price", {"type": ["number", "null"]})

    add("revenue", "units_per_week_capacity", {"type": "number"})
    add("revenue", "avg_units_per_week_year1", {"type": ["number", "null"]})
    add("revenue", "utilization_rate", {"type": ["number", "null"]})
    add("revenue", "operating_weeks_per_year", {"type": "number"})
    add("revenue", "unit_price", {"type": ["number", "null"]})

    add("marketing", "monthly_marketing_budget", {"type": ["number", "null"]})
    add("marketing", "primary_channels", {"type": ["string", "null"]})

    add("headcount", "roles", {"type": "array", "items": {"type": "object"}})

    add("fulfillment", "fulfillment_model", {"type": ["string", "null"]})
    add("fulfillment", "who_fulfills", {"type": ["string", "null"]})
    add("fulfillment", "lead_time", {"type": ["string", "null"]})

    add("ops_concept", "operating_unit", {"type": ["string", "null"]})
    add("ops_concept", "primary_constraint", {"type": ["string", "null"]})
    add("ops_concept", "process_overview", {"type": ["string", "null"]})

    add("milestones", "milestones", {"type": "array", "items": {"type": "object"}})

    # Operating expense models (stored on the unified consult draft)
    add("cogs", "cost_per_unit", {"type": ["number", "null"]})
    add("cogs", "materials_cost_per_unit", {"type": ["number", "null"]})
    add("cogs", "direct_fulfillment_cost_per_unit", {"type": ["number", "null"]})
    add("cogs", "other_variable_cost_per_unit", {"type": ["number", "null"]})
    add("cogs", "cogs_percent_of_revenue", {"type": ["number", "null"]})

    add("gna", "monthly_rent_expense", {"type": ["number", "null"]})
    add("gna", "other_operating_expense", {"type": ["number", "null"]})
    add("gna", "other_monthly_debt_payments", {"type": ["number", "null"]})
    add("gna", "monthly_software_expense", {"type": ["number", "null"]})
    add("gna", "monthly_insurance_expense", {"type": ["number", "null"]})
    add("gna", "monthly_utilities_expense", {"type": ["number", "null"]})
    add("gna", "monthly_admin_expense", {"type": ["number", "null"]})

    return schemas

  if consult_type_norm == "ops":
    return {
      "consumer_type": {"type": "string", "enum": ["consumer", "b2b", "mixed"]},
      "business_type": {"type": "string"},
      "business_description_summary": {"type": "string"},
      "unit_name": {"type": "string"},
      "unit_description": {"type": "string"},
      "units_per_week_capacity": {"type": "number"},
      # unit_price is intentionally optional for multi-stream businesses.
      # When not applicable, it is represented as null (not 0).
      "unit_price": {"type": ["number", "null"]},
      # starting_revenue is a forward-looking, normalized Year-1 operating-year forecast.
      "starting_revenue": {"type": "number"},
      "shipping_method": {"type": "string"},
      "sales_modality": {"type": "string", "enum": ["physical", "online", "hybrid"]},
      "geographic_scope": {"type": "string", "enum": ["local", "regional", "national", "international"]},
      "geographic_coverage": {"type": "string"},
      "countries": {"type": "array", "items": {"type": "string"}},
      "milestones": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "description": {"type": "string"},
            "timing": {"type": "string"},
          },
          "required": ["description", "timing"],
        },
      },
      "capacity_driver": {"type": "string", "enum": ["labor", "system", "demand"]},
      "primary_growth_lever": {"type": "string"},
      "initial_assets": {"type": "number"},
      "initial_lease": {"type": "string"},
      "initial_equity": {"type": "number"},
      "total_debt_outstanding": {"type": "number"},
      "legal_entity": {"type": "string"},
      "confidence": {"type": "number"},
    }

  if consult_type_norm == "target_market":
    return {
      "consumer_type": {"type": "string", "enum": ["consumer", "b2b", "mixed"]},
      "gender_age_intent": {
        "type": ["array", "null"],
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "gender_focus": {"type": "string", "enum": ["female", "male", "all"]},
            "age_min": {"type": "number"},
            "age_max": {"type": "number"},
          },
          "required": ["gender_focus", "age_min", "age_max"],
        },
      },
      "income_intent": {
        "type": ["array", "null"],
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "income_min": {"type": "number"},
            "income_max": {"type": "number"},
          },
          "required": ["income_min", "income_max"],
        },
      },
      "selections": {
        "type": ["array", "null"],
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "segment": {
              "type": "string",
              "enum": [
                "Education",
                "Household Structure",
                "Housing Economics",
                "Employment",
              ],
            },
            "acs_codes": {"type": "array", "items": {"type": "string"}},
          },
          "required": ["segment", "acs_codes"],
        },
      },
      "b2b_industry_terms": {"type": ["array", "null"], "items": {"type": "string"}},
      "b2b_naics_6": {
        "type": ["array", "null"],
        "items": {"type": "string", "pattern": "^[0-9]{6}$"},
        "minItems": 1,
        "maxItems": 20,
      },
      "b2b_size_bands": {
        "type": ["array", "null"],
        "items": {
          "type": "string",
          "enum": [
            "1-4",
            "5-9",
            "10-19",
            "20-99",
            "100-499",
            "500-999",
            "1000-2499",
            "2500-4999",
            "5000-9999",
            "10000+",
          ],
        },
      },
      "b2b_age_bands": {
        "type": ["array", "null"],
        "items": {
          "type": "string",
          "enum": [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6-10",
            "11-15",
            "16-20",
            "21-25",
            "26+",
          ],
        },
      },
      "target_market_summary": {"type": "string"},
      "confidence": {"type": "number"},
    }

  if consult_type_norm == "people":
    return {
      "people": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "full_name": {"type": "string"},
            "role_title": {"type": "string"},
            "primary_responsibilities": {"type": "string"},
            "relevant_background": {"type": "string"},
            "experience_years": {"type": "string"},
            "why_strengthens_business": {"type": "string"},
            "paragraph": {"type": "string"},
          },
          "required": [
            "full_name",
            "role_title",
            "primary_responsibilities",
            "relevant_background",
            "experience_years",
            "why_strengthens_business",
            "paragraph",
          ],
        },
      },
      "key_people_summary": {"type": "string"},
      "confidence": {"type": "number"},
    }

  if consult_type_norm == "financials":
    return {
      "financials_summary": {"type": "string"},
      "current_revenue": {"type": "number"},
      "current_cogs": {"type": "number"},
      "other_operating_expense": {"type": "number"},
      "monthly_rent_expense": {"type": "number"},
      "other_monthly_debt_payments": {"type": "number"},
      "current_payroll": {"type": "number"},
      "current_num_employees": {"type": "number"},
      "current_capex": {"type": "number"},
      "ar_balance": {"type": "number"},
      "ap_balance": {"type": "number"},
      "inventory_balance": {"type": "number"},
      "total_debt_outstanding": {"type": "number"},
      "annual_interest_payment": {"type": "number"},
      "annual_principal_payment": {"type": "number"},
      "owner_compensation": {"type": "number"},
      "cash_on_hand": {"type": "number"},
      "confidence": {"type": "number"},
    }

  raise ValueError(f"Unknown consult_type={consult_type!r}")


def _parse_number_value_json(raw: str) -> Optional[float]:
  """
  Best-effort parse for value_json when the model returns a number-like string
  that is not valid JSON (e.g. "$504", "18.5k", "504/month").

  This is NOT intent inference; it only coerces an already-selected patch field
  to a numeric value when possible.
  """
  text = str(raw or "").strip()
  if not text:
    return None

  lowered = text.lower().strip()
  if lowered in ("none", "n/a", "na", "null", "unknown"):
    return None

  # Remove common currency/formatting noise.
  cleaned = lowered.replace(",", "")
  cleaned = cleaned.replace("$", "").replace("usd", "").strip()

  # Extract the first number token with optional k/m/b shorthand.
  match = re.search(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<suffix>[kmb])?", cleaned)
  if not match:
    return None

  try:
    num = float(match.group("num"))
  except Exception:
    return None

  suffix = (match.group("suffix") or "").strip().lower()
  if suffix == "k":
    num *= 1_000
  elif suffix == "m":
    num *= 1_000_000
  elif suffix == "b":
    num *= 1_000_000_000

  if not (num >= 0):
    return None
  return num


def _final_schema(*, allowed_patch_fields: Sequence[str], consult_type: str) -> Dict[str, Any]:
  """
  OpenAI strict json_schema requires:
  - every object schema must include additionalProperties: false
  - every object schema must include required listing ALL keys in properties

  Sparse patch objects with optional keys are not compatible.
  We represent a patch as an array of operations:
    [{ "field": "unit_price", "value_json": "10000" }]
  where value_json is a JSON-encoded value string (parsed deterministically server-side).

  NOTE: OpenAI's json_schema subset rejects oneOf/anyOf in response schemas.
  """
  return {
    "name": "consult_intent_router",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "action": {
          "type": "string",
          "enum": [
            "edit_patch",
            "answer_readonly",
            "continue_chat",
          ],
        },
        "assistant_message": {"type": "string"},
        "patch": {
          # OpenAI structured outputs rejects union types here (it surfaces as an implicit oneOf),
          # so patch is always an array. For non-edit actions, the model must return [].
          "type": "array",
          "minItems": 0,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "field": {"type": "string", "enum": list(allowed_patch_fields)},
              "value_json": {"type": "string"},
            },
            "required": ["field", "value_json"],
          },
        },
      },
      "required": ["action", "assistant_message", "patch"],
    },
  }


def _last_assistant_message(messages: Sequence[Dict[str, Any]]) -> str:
  for msg in reversed(list(messages)):
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    content = str(msg.get("content") or "").strip()
    if content:
      return content
  return ""


def _humanize_patch_field(field: str) -> str:
  raw = str(field or "").strip()
  if not raw:
    return "that value"
  if raw.count(".") == 1:
    _, tail = raw.split(".", 1)
  else:
    tail = raw
  return tail.replace("_", " ")


def _coerce_value_json(*, value_json_raw: str, allowed_types: list[str]) -> tuple[bool, Any]:
  """
  Server-side safety net to prevent user-facing 500s when the model returns an
  invalid value_json string. This does NOT guess intent; it only coerces types
  for an already-selected field.
  """
  raw = str(value_json_raw or "").strip()
  if not raw:
    if "number" in allowed_types and "null" in allowed_types:
      return True, None
    if "number" in allowed_types:
      return True, 0.0
    if "string" in allowed_types:
      return True, ""
    if "array" in allowed_types:
      return True, []
    if "object" in allowed_types:
      return True, {}
    return False, None

  if "null" in allowed_types and raw.lower() in ("none", "n/a", "na", "null", "unknown"):
    return True, None

  try:
    return True, json.loads(raw)
  except Exception:
    pass

  if "number" in allowed_types:
    parsed_num = _parse_number_value_json(raw)
    if parsed_num is None:
      return False, None
    return True, parsed_num

  if "string" in allowed_types:
    # Accept raw string without JSON quoting as a last resort.
    return True, raw

  if "array" in allowed_types:
    if raw.lower() in ("none", "n/a", "na", "null", "unknown"):
      return True, []
    return False, None

  if "object" in allowed_types:
    if raw.lower() in ("none", "n/a", "na", "null", "unknown"):
      return True, {}
    return False, None

  return False, None


def route_intent(
  *,
  consult_type: str,
  user_message: str,
  baseline_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  recent_messages: Sequence[Dict[str, Any]] | None = None,
  confirm_question_override: str | None = None,
  active_focus: str | None = None,
) -> Dict[str, Any]:
  """
  GPT-only intent router for post-completion messages.

  This function is the sole authority for interpreting user intent:
  - confirmation vs. objection vs. ambiguity
  - which field(s) the user intends to change
  - numeric normalization (e.g., 10k -> 10000)

  Returns:
    { action, assistant_message, patch }
  """
  consult_type_norm = str(consult_type or "").strip().lower()
  if consult_type_norm not in ("ops", "target_market", "people", "financials", "unified"):
    raise ValueError(f"Unknown consult_type={consult_type!r}")

  api_key = _require_openai_key()
  model = _openai_model()

  _ = confirm_question_override

  allowed_fields = {
    "ops": [
      "consumer_type",
      "business_type",
      "unit_name",
      "unit_description",
      "units_per_week_capacity",
      "unit_price",
      "starting_revenue",
      "shipping_method",
      "sales_modality",
      "geographic_scope",
      "geographic_coverage",
      "countries",
      "milestones",
      "capacity_driver",
      "primary_growth_lever",
      "initial_assets",
      "initial_lease",
      "initial_equity",
      "total_debt_outstanding",
      "legal_entity",
    ],
    "target_market": [
      "consumer_type",
      "gender_age_intent",
      "income_intent",
      "selections",
      "b2b_industry_terms",
      "b2b_naics_6",
      "b2b_size_bands",
      "b2b_age_bands",
    ],
    "people": [
      "people",
    ],
    "financials": [
      "current_revenue",
      "current_cogs",
      "other_operating_expense",
      "monthly_rent_expense",
      "other_monthly_debt_payments",
      "current_payroll",
      "current_num_employees",
      "current_capex",
      "ar_balance",
      "ap_balance",
      "inventory_balance",
      "total_debt_outstanding",
      "annual_interest_payment",
      "annual_principal_payment",
      "owner_compensation",
      "cash_on_hand",
    ],
    "unified": [
      "business.name",
      "business.address",
      "business.start_date",
      "pricing.unit_price",
      "revenue.units_per_week_capacity",
      "revenue.avg_units_per_week_year1",
      "revenue.utilization_rate",
      "revenue.operating_weeks_per_year",
      "revenue.unit_price",
      "marketing.monthly_marketing_budget",
      "marketing.primary_channels",
      "headcount.roles",
      "fulfillment.fulfillment_model",
      "fulfillment.who_fulfills",
      "fulfillment.lead_time",
      "ops_concept.operating_unit",
      "ops_concept.primary_constraint",
      "ops_concept.process_overview",
      "milestones.milestones",
      "cogs.cost_per_unit",
      "cogs.materials_cost_per_unit",
      "cogs.direct_fulfillment_cost_per_unit",
      "cogs.other_variable_cost_per_unit",
      "cogs.cogs_percent_of_revenue",
      "gna.monthly_rent_expense",
      "gna.other_operating_expense",
      "gna.other_monthly_debt_payments",
      "gna.monthly_software_expense",
      "gna.monthly_insurance_expense",
      "gna.monthly_utilities_expense",
      "gna.monthly_admin_expense",
      *[f"ops.{f}" for f in _value_schema_by_consult_field(consult_type="ops").keys() if f in {
        "consumer_type",
        "business_type",
        "unit_name",
        "unit_description",
        "units_per_week_capacity",
        "unit_price",
        "starting_revenue",
        "shipping_method",
        "sales_modality",
        "geographic_scope",
        "geographic_coverage",
        "countries",
        "milestones",
        "capacity_driver",
        "primary_growth_lever",
        "initial_assets",
        "initial_lease",
        "initial_equity",
        "total_debt_outstanding",
        "legal_entity",
      }],
      *[f"market.{f}" for f in _value_schema_by_consult_field(consult_type="target_market").keys() if f in {
        "consumer_type",
        "gender_age_intent",
        "income_intent",
        "selections",
        "b2b_industry_terms",
        "b2b_naics_6",
        "b2b_size_bands",
        "b2b_age_bands",
      }],
      *[f"people.{f}" for f in _value_schema_by_consult_field(consult_type="people").keys() if f in {
        "people",
      }],
      *[f"financials.{f}" for f in _value_schema_by_consult_field(consult_type="financials").keys() if f in {
        "current_revenue",
        "current_cogs",
        "other_operating_expense",
        "monthly_rent_expense",
        "other_monthly_debt_payments",
        "current_payroll",
        "current_num_employees",
        "current_capex",
        "ar_balance",
        "ap_balance",
        "inventory_balance",
        "total_debt_outstanding",
        "annual_interest_payment",
        "annual_principal_payment",
        "owner_compensation",
        "cash_on_hand",
      }],
    ],
  }[consult_type_norm]

  recent_messages_list = list(recent_messages or [])
  last_assistant = _last_assistant_message(recent_messages_list)

  system = f"""
You are the intent router for a multi-step business intake app.

Non-negotiable rule:
- You are the SOLE authority for interpreting the user's intent. Do NOT defer intent decisions to any frontend/back-end heuristics.

You are operating on any message for the "{consult_type_norm}" consult.

You are given:
- baseline_json: the last confirmed structured output for this consult (canonical baseline)
- shared_context: read-only outputs from other consults
- last_assistant_message: the most recent assistant message shown to the user
- user_message: the new user message

Your job is to decide what the user meant, like a human consultant would.

Output ONLY JSON matching the schema.

Actions:
IMPORTANT: Valid actions are: edit_patch, answer_readonly, continue_chat. Do NOT return confirm_proceed or confirm_clarify.
1) confirm_proceed
  - Use when the user is clearly agreeing / confirming OR their response does not express disagreement, uncertainty, or a request to change something.
  - Objection-first model: if they are not objecting, proceed.
2) confirm_clarify
  - Use when the user message is ambiguous/contradictory/uncertain and you cannot confidently infer whether they want changes or want to proceed.
  - assistant_message MUST be a single, brief clarifying question.
  - The clarifying question MUST match the current focus's framing:
    - If active_focus is "financials": anchor to "as of last month" and do NOT ask for 12-month/year totals; if a monthly amount is natural, ask for the monthly amount.
    - If active_focus is "ops", "market", or "people": ask only for the one missing detail needed to proceed, with no bundled questions.
3) edit_patch
   - Use when the user is providing OR correcting one or more canonical facts that should be recorded in the draft (including normal answers to intake questions), regardless of what stage the consult is currently in.
   - IMPORTANT: If the last assistant message PROPOSED a specific change to one or more facts (e.g., "Should we update X to 700?")
     and the user clearly agrees (yes/ok/sure/that’s right), you MUST return edit_patch with the proposed patch.
     In that scenario, do NOT return continue_chat.
   - DO NOT treat a simple "yes" to an in-section check like "Is that correct?" as an edit_patch unless a concrete new value/change was explicitly proposed.
   - patch MUST be an array of operations. Each operation is an object:
       {{ "field": "<field_name>", "value_json": "<JSON-encoded value>" }}
     - value_json MUST be a JSON snippet encoded as a string:
       - numbers: digits only, e.g. "504" or "18.5" (no $ signs, no commas, no "/month")
      - strings: a valid JSON string, e.g. "\"monthly\""
      - arrays/objects: valid JSON like "[\"US\"]" or "{{\"a\":1}}"
  - You MUST normalize values:
    - numeric shorthand like 10k/10K -> 10000, 1.2m -> 1200000
    - currency words/symbols to plain numbers (numbers must be JSON numbers, not strings)
  - patch MUST contain ONLY the field(s) that should change (no full rewrites).
  - patch field names MUST stay within the allowed fields list: {json.dumps(allowed_fields, ensure_ascii=False)}.
  - For edit_patch, assistant_message MUST be short and conversational:
    - briefly acknowledge the specific change(s)
    - do NOT rewrite or re-summarize the entire section
    - do NOT ask multi-part questions
4) answer_readonly
  - Use when the user is asking a question that is NOT a change request and is not an approval/disapproval of the summary.
  - Answer using baseline_json + shared_context (read-only). Do NOT apply any patch (patch=[]).
  - Keep it short and directly answer the user's question. Do not reprint the full baseline summary.
5) continue_chat
  - Use when the user message does NOT supply any canonical fact that should be recorded (no patch).
  - patch MUST be [].

Interpretation rules:
- In unified mode, ALWAYS capture canonical facts the user provides, even if they belong to a different section than active_focus.
  Example: if active_focus is "ops" but the user says "Monthly rent is 1500", return edit_patch for financials.monthly_rent_expense.
- Revenue timing disambiguation:
  - ops.starting_revenue is a forward-looking Year-1 operating-year forecast (e.g., "Year 1 revenue", "projected first-year revenue", "starting revenue after launch").
  - financials.current_revenue is revenue today / recent run-rate (e.g., "current annual revenue", "last 12 months revenue", "revenue so far").
- During active_focus "ops", "market", "people", or "financials", if the user is answering the current question by supplying a concrete value/detail that should be recorded as a canonical fact (including "0"/"none" answers that imply 0), prefer edit_patch over continue_chat so the draft stays current and downstream projections (including cards) reflect the latest values immediately.
- If the user says something like "10000, not 10" after correcting unit price, infer they are correcting the same thing again (do not require keywords).
- If the user corrects business identity details (name, address, start date) anywhere in the conversation, treat it as an edit_patch to business.name / business.address / business.start_date (unified mode uses scoped fields).
- For business.start_date, normalize to ISO format YYYY-MM-DD when the user provides a specific date.
- Internal Ops classification (unified mode, never shown to the client):
  - If active_focus is "ops", baseline_json.ops.business_type is empty, and baseline_json.business_type_candidates is present,
    then when the user is clearly confirming the initial business restatement ("yes/correct/looks right"),
    return edit_patch setting ops.business_type to the single best match from business_type_candidates (and ops.consumer_type if inferable).
  - Do NOT mention the business_type label or any NAICS codes in assistant_message.
- If the user's intent is clear, proceed confidently; do not re-ask for confirmation.
- If the user disagrees or requests changes, treat it as edit_patch.
- If the user is agreeing to a proposed fact update from the last assistant message, treat it as edit_patch and apply that update.

Unified mode:
- If consult_type is "unified", patch fields must be scoped as "<group>.<field>" (e.g., "ops.unit_price", "financials.current_revenue", "business.name").
- Only patch the specific intended facts; do not rewrite summaries.
- Unified mode also supports model-card driver updates (stored on the unified draft):
  - pricing.unit_price
  - revenue.* drivers (units_per_week_capacity, avg_units_per_week_year1, utilization_rate, operating_weeks_per_year, unit_price)
  - marketing.* drivers (monthly_marketing_budget, primary_channels)
  - headcount.roles (array of role objects; prefer fields like role_title, employee_count, hours_per_week, weeks_per_year, hourly_rate_override when the user provides them)
    - IMPORTANT: staffing/headcount/hiring plans belong in headcount.roles. Do NOT store them in people.people (key individuals) and do NOT store Year-1 staffing plans in financials.current_payroll/current_num_employees unless the user explicitly says those are current/today values.
  - fulfillment.* drivers (fulfillment_model, who_fulfills, lead_time)
  - ops_concept.* drivers (operating_unit, primary_constraint, process_overview)
  - milestones.milestones (array of milestone objects; include at least a human title and a target period/date when possible)

Return JSON only. No prose.
""".strip()

  context = {
    "consult_type": consult_type_norm,
    "active_focus": str(active_focus or "").strip().lower() or None,
    "baseline_json": baseline_json,
    "shared_context": shared_context,
    "last_assistant_message": last_assistant,
    "user_message": str(user_message or "").strip(),
  }
  context_blob = json.dumps(context, ensure_ascii=False, default=_json_default)

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  schema_wrapper = _final_schema(allowed_patch_fields=allowed_fields, consult_type=consult_type_norm)
  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": context_blob},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema_wrapper["name"],
        "schema": schema_wrapper["schema"],
        "strict": True,
      }
    },
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")

  data = resp.json()
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        result = part["json"]
        action = str(result.get("action") or "").strip()
        patch_ops = result.get("patch")

        if action != "edit_patch":
          # For non-edit actions, enforce read-only semantics: no patch application.
          result["patch"] = None
          return result

        if not isinstance(patch_ops, list) or not patch_ops:
          # Safety: if the model selected edit_patch but provided no operations,
          # treat this as a normal conversational turn instead of crashing the flow.
          # This preserves "GPT-only intent" while keeping the intake usable.
          return {"action": "continue_chat", "assistant_message": "", "patch": None}

        value_schemas = _value_schema_by_consult_field(consult_type=consult_type_norm)
        patch_dict: Dict[str, Any] = {}
        for op in patch_ops:
          if not isinstance(op, dict):
            continue
          field = str(op.get("field") or "").strip()
          value_json_raw = str(op.get("value_json") or "").strip()
          if not field:
            continue
          if field not in allowed_fields:
            raise RuntimeError(f"Intent router returned disallowed patch field: {field}")
          expected_schema = value_schemas.get(field) if isinstance(value_schemas.get(field), dict) else {}
          expected_types = expected_schema.get("type")
          allowed_types: list[str] = []
          if isinstance(expected_types, str):
            allowed_types = [expected_types]
          elif isinstance(expected_types, list):
            allowed_types = [str(t) for t in expected_types if isinstance(t, str)]
          ok, value = _coerce_value_json(value_json_raw=value_json_raw, allowed_types=allowed_types)
          if not ok:
            return {"action": "continue_chat", "assistant_message": "", "patch": None}

          if allowed_types:
            if value is None:
              if "null" not in allowed_types:
                return {"action": "continue_chat", "assistant_message": "", "patch": None}
            elif isinstance(value, bool):
              if "boolean" not in allowed_types:
                return {"action": "continue_chat", "assistant_message": "", "patch": None}
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
              if "number" not in allowed_types:
                return {"action": "continue_chat", "assistant_message": "", "patch": None}
            elif isinstance(value, str):
              if "string" not in allowed_types:
                return {"action": "continue_chat", "assistant_message": "", "patch": None}
            elif isinstance(value, list):
              if "array" not in allowed_types:
                return {"action": "continue_chat", "assistant_message": "", "patch": None}
            elif isinstance(value, dict):
              if "object" not in allowed_types:
                return {"action": "continue_chat", "assistant_message": "", "patch": None}

          patch_dict[field] = value

        result["patch"] = patch_dict
        return result

  # Fallback: parse output_text as JSON (should be rare with strict schema).
  text_chunks: list[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        text_chunks.append(str(part["text"]))
  raw = "\n".join(text_chunks).strip()
  parsed = json.loads(raw)
  if not isinstance(parsed, dict):
    raise RuntimeError("Intent router did not return a JSON object.")
  # Mirror normalization done in the output_json path.
  action = str(parsed.get("action") or "").strip()
  patch_ops = parsed.get("patch")
  if action != "edit_patch":
    parsed["patch"] = None
    return parsed
  if not isinstance(patch_ops, list) or not patch_ops:
    # Safety: if the model selected edit_patch but provided no operations,
    # treat this as a normal conversational turn instead of crashing the flow.
    return {"action": "continue_chat", "assistant_message": "", "patch": None}
  value_schemas = _value_schema_by_consult_field(consult_type=consult_type_norm)
  patch_dict: Dict[str, Any] = {}
  for op in patch_ops:
    if not isinstance(op, dict):
      continue
    field = str(op.get("field") or "").strip()
    value_json_raw = str(op.get("value_json") or "").strip()
    if not field:
      continue
    if field not in allowed_fields:
      raise RuntimeError(f"Intent router returned disallowed patch field: {field}")
    expected_schema = value_schemas.get(field) if isinstance(value_schemas.get(field), dict) else {}
    expected_types = expected_schema.get("type")
    allowed_types: list[str] = []
    if isinstance(expected_types, str):
      allowed_types = [expected_types]
    elif isinstance(expected_types, list):
      allowed_types = [str(t) for t in expected_types if isinstance(t, str)]
    ok, value = _coerce_value_json(value_json_raw=value_json_raw, allowed_types=allowed_types)
    if not ok:
      parsed["action"] = "continue_chat"
      parsed["assistant_message"] = ""
      parsed["patch"] = None
      return parsed

    if allowed_types:
      if value is None:
        if "null" not in allowed_types:
          parsed["action"] = "continue_chat"
          parsed["assistant_message"] = ""
          parsed["patch"] = None
          return parsed
      elif isinstance(value, bool):
        if "boolean" not in allowed_types:
          parsed["action"] = "continue_chat"
          parsed["assistant_message"] = ""
          parsed["patch"] = None
          return parsed
      elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "number" not in allowed_types:
          parsed["action"] = "continue_chat"
          parsed["assistant_message"] = ""
          parsed["patch"] = None
          return parsed
      elif isinstance(value, str):
        if "string" not in allowed_types:
          parsed["action"] = "continue_chat"
          parsed["assistant_message"] = ""
          parsed["patch"] = None
          return parsed
      elif isinstance(value, list):
        if "array" not in allowed_types:
          parsed["action"] = "continue_chat"
          parsed["assistant_message"] = ""
          parsed["patch"] = None
          return parsed
      elif isinstance(value, dict):
        if "object" not in allowed_types:
          parsed["action"] = "continue_chat"
          parsed["assistant_message"] = ""
          parsed["patch"] = None
          return parsed

    patch_dict[field] = value
  parsed["patch"] = patch_dict
  return parsed
