from __future__ import annotations

import json
import os
import re
import time
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

    # fulfillment
    for k, v in _value_schema_by_consult_field(consult_type="fulfillment").items():
      add("fulfillment", k, v)

    return schemas

  if consult_type_norm == "ops":
    return {
      "consumer_type": {"type": "string", "enum": ["consumer", "b2b", "mixed"]},
      "business_type": {"type": "string"},
      "business_description_summary": {"type": "string"},
      "unit_name": {"type": "string"},
      "unit_description": {"type": "string"},
      "units_per_week_capacity": {"type": "number"},
      "unit_price": {"type": "number"},
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

  if consult_type_norm == "fulfillment":
    return {
      "time": {"type": "string"},
      "personnel": {"type": "string"},
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
            "confirm_proceed",
            "confirm_clarify",
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
    if "number" in allowed_types:
      return True, 0.0
    if "string" in allowed_types:
      return True, ""
    if "array" in allowed_types:
      return True, []
    if "object" in allowed_types:
      return True, {}
    return False, None

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

  confirm_questions = {
    "ops": "Does this look right before we move on to Customers & Positioning?",
    "target_market": "Does this look right before we move on to People & Capability?",
    "people": "Does this look right before we move on to Financials?",
    "financials": "Does this look right before we move on to Submit intake?",
    "unified": "Does this look right before we move on?",
  }
  if confirm_question_override is None:
    confirm_question = str(confirm_questions[consult_type_norm]).strip()
  else:
    confirm_question = str(confirm_question_override).strip()

  allowed_fields = {
    "ops": [
      "consumer_type",
      "business_type",
      "unit_name",
      "unit_description",
      "units_per_week_capacity",
      "unit_price",
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
      *[f"ops.{f}" for f in _value_schema_by_consult_field(consult_type="ops").keys() if f in {
        "consumer_type",
        "business_type",
        "unit_name",
        "unit_description",
        "units_per_week_capacity",
        "unit_price",
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
      *[f"fulfillment.{f}" for f in _value_schema_by_consult_field(consult_type="fulfillment").keys() if f in {
        "time",
        "personnel",
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
1) confirm_proceed
  - Use when the user is clearly agreeing / confirming OR their response does not express disagreement, uncertainty, or a request to change something.
  - Objection-first model: if they are not objecting, proceed.
2) confirm_clarify
  - Use when the user message is ambiguous/contradictory/uncertain and you cannot confidently infer whether they want changes or want to proceed.
  - assistant_message MUST be a single, brief clarifying question.
3) edit_patch
  - Use when the user is requesting a correction/update to ANY already-captured fact in the canonical intake model (even if phrased casually), regardless of what stage the consult is currently in.
  - IMPORTANT: If the last assistant message PROPOSED a specific change to one or more facts (e.g., "Should we update X to 700?")
    and the user clearly agrees (yes/ok/sure/that’s right), you MUST return edit_patch with the proposed patch.
    In that scenario, do NOT return confirm_proceed.
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
  - Use when the user is answering the current question and the consult should continue normally (no patch, no confirmation decision).
  - patch MUST be [].

Interpretation rules:
- If the user says something like "10000, not 10" after correcting unit price, infer they are correcting the same thing again (do not require keywords).
- If the user corrects business identity details (name, address, start date) anywhere in the conversation, treat it as an edit_patch to business.name / business.address / business.start_date (unified mode uses scoped fields).
- For business.start_date, normalize to ISO format YYYY-MM-DD when the user provides a specific date.
- If the user's intent is clear, proceed confidently; do not re-ask for confirmation.
- If the user disagrees or requests changes, treat it as edit_patch.
- If the user is agreeing to a proposed fact update from the last assistant message, treat it as edit_patch and apply that update.
- If the last assistant message described the fulfillment model (who performs it + typical timing) and the user agrees, set fulfillment.personnel and fulfillment.time accordingly.

Consistency inference (active_focus == "consistency"):
- If the last assistant message offered reconciliation choices (A/B/C or similar) and the user picks one
  (letter, short phrase, or a clear paraphrase), return edit_patch and apply the implied update.
- Use baseline_json values for amounts when available (especially financials.other_operating_expense).
- A / personal funds / owner funding -> increase ops.initial_equity by that amount (add to existing ops.initial_equity if numeric).
- B / card / loan / debt / payable -> set financials.ap_balance to that amount (use financials.total_debt_outstanding only if the user explicitly says loan/debt).
- C / not spent / change expenses to 0 -> set financials.other_operating_expense to 0.
- Do NOT ask for confirmation in this case; acknowledge and apply.

Unified mode:
- If consult_type is "unified", patch fields must be scoped as "<group>.<field>" (e.g., "ops.unit_price", "financials.current_revenue", "business.name").
- Only patch the specific intended facts; do not rewrite summaries.
- Field hints:
  - fulfillment.personnel = who performs the work (owner, staff, contractors, platform, etc.).
  - fulfillment.time = typical timing/lead time (e.g., same-day, weekly cadence, 2-4 weeks).

Return JSON only. No prose.
""".strip()

  context = {
    "consult_type": consult_type_norm,
    "active_focus": str(active_focus or "").strip().lower() or None,
    "baseline_json": baseline_json,
    "shared_context": shared_context,
    "last_assistant_message": last_assistant,
    "user_message": str(user_message or "").strip(),
    "confirm_question": confirm_question,
  }
  context_blob = json.dumps(context, ensure_ascii=False)

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
          raise RuntimeError("Intent router returned edit_patch without a patch operations array.")

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
            return {
              "action": "confirm_clarify",
              "assistant_message": f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value.",
              "patch": None,
            }

          if allowed_types:
            if value is None:
              if "null" not in allowed_types:
                return {
                  "action": "confirm_clarify",
                  "assistant_message": f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value.",
                  "patch": None,
                }
            elif isinstance(value, bool):
              if "boolean" not in allowed_types:
                return {
                  "action": "confirm_clarify",
                  "assistant_message": f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value.",
                  "patch": None,
                }
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
              if "number" not in allowed_types:
                return {
                  "action": "confirm_clarify",
                  "assistant_message": f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value.",
                  "patch": None,
                }
            elif isinstance(value, str):
              if "string" not in allowed_types:
                return {
                  "action": "confirm_clarify",
                  "assistant_message": f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value.",
                  "patch": None,
                }
            elif isinstance(value, list):
              if "array" not in allowed_types:
                return {
                  "action": "confirm_clarify",
                  "assistant_message": f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value.",
                  "patch": None,
                }
            elif isinstance(value, dict):
              if "object" not in allowed_types:
                return {
                  "action": "confirm_clarify",
                  "assistant_message": f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value.",
                  "patch": None,
                }

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
    raise RuntimeError("Intent router returned edit_patch without a patch operations array.")
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
      parsed["action"] = "confirm_clarify"
      parsed["assistant_message"] = (
        f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value."
      )
      parsed["patch"] = None
      return parsed

    if allowed_types:
      if value is None:
        if "null" not in allowed_types:
          parsed["action"] = "confirm_clarify"
          parsed["assistant_message"] = (
            f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value."
          )
          parsed["patch"] = None
          return parsed
      elif isinstance(value, bool):
        if "boolean" not in allowed_types:
          parsed["action"] = "confirm_clarify"
          parsed["assistant_message"] = (
            f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value."
          )
          parsed["patch"] = None
          return parsed
      elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "number" not in allowed_types:
          parsed["action"] = "confirm_clarify"
          parsed["assistant_message"] = (
            f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value."
          )
          parsed["patch"] = None
          return parsed
      elif isinstance(value, str):
        if "string" not in allowed_types:
          parsed["action"] = "confirm_clarify"
          parsed["assistant_message"] = (
            f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value."
          )
          parsed["patch"] = None
          return parsed
      elif isinstance(value, list):
        if "array" not in allowed_types:
          parsed["action"] = "confirm_clarify"
          parsed["assistant_message"] = (
            f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value."
          )
          parsed["patch"] = None
          return parsed
      elif isinstance(value, dict):
        if "object" not in allowed_types:
          parsed["action"] = "confirm_clarify"
          parsed["assistant_message"] = (
            f"Just to confirm, what should we record for {_humanize_patch_field(field)}? Please give a single number or short value."
          )
          parsed["patch"] = None
          return parsed

    patch_dict[field] = value
  parsed["patch"] = patch_dict
  return parsed
