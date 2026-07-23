from __future__ import annotations



import json

import os

import re

import time

from pathlib import Path

from typing import Any, Dict, List, Optional, Sequence, Tuple



import requests
try:
  from openai_http import post_openai_with_retries  # type: ignore
except Exception:
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore



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





def _require_openai_key() -> str:

  _load_root_env()

  key = (os.getenv("OPENAI_API_KEY") or "").strip()

  if not key:

    raise RuntimeError("OPENAI_API_KEY is not configured.")

  return key





def _openai_model() -> str:

  _load_root_env()

  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"





def _openai_timeout_seconds() -> Optional[int]:

  _load_root_env()

  return None





def _format_openai_error(resp: requests.Response) -> str:

  if resp.status_code in _RETRYABLE_STATUS:

    return "We're having trouble reaching our AI service right now. Please try again in a minute."

  return f"OpenAI API error {resp.status_code}: {resp.text[:500]}"





def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  return post_openai_with_retries(
    url=url,
    headers=headers,
    payload=payload,
    timeout_seconds=timeout,
    retryable_status=_RETRYABLE_STATUS,
    max_attempts=3,
  )





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

    add("business", "address_street", {"type": "string"})

    add("business", "address_city", {"type": "string"})

    add("business", "address_state", {"type": "string"})

    add("business", "address_zip", {"type": "string"})

    add("business", "address_country", {"type": "string"})



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

    # coherence (the viability-gap lever conversation at the end of
    # financials): option = an offered option id; parked = the client
    # wants to pause; ops.product_overrides carries custom per-line
    # prices there (same object shape as the financials_year1 field).
    add("coherence", "option", {"type": "string"})
    add("coherence", "parked", {"type": "boolean"})
    if "ops.product_overrides" not in schemas:
      add("ops", "product_overrides", {"type": "object"})

    return schemas



  if consult_type_norm == "ops":

    return {

      "consumer_type": {"type": "string", "enum": ["consumer", "b2b", "mixed"]},

      "business_type": {"type": "string"},

      "business_description_summary": {"type": "string"},

      "unit_name": {"type": "string"},

      "unit_description": {"type": "string"},

      "unit_cadence": {"type": "string", "enum": ["weekly", "monthly", "contract"]},

      "units_per_week_capacity": {"type": "number"},

      "units_per_period_capacity": {"type": "number"},

      "operating_periods_per_year": {"type": "number"},

      "unit_price": {"type": "number"},
      "shipping_method": {"type": "string"},
      "sales_modality": {"type": "string", "enum": ["physical", "online", "hybrid"]},
      "geographic_scope": {"type": "string", "enum": ["local", "regional", "national", "international"]},
      "geographic_coverage": {"type": "string"},
      "countries": {"type": "array", "items": {"type": "string"}},
      "competitive_advantage": {"type": "string"},
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

      "legal_entity": {"type": "string"},

      "lob_models": {"type": ["array", "null"]},

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

      "marketing_plan_summary": {"type": "string"},

      "confidence": {"type": "number"},

    }



  if consult_type_norm == "people":

    return {

      "rest_of_team_payroll_year1": {"type": "number"},

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

            "annual_wage": {"type": ["number", "null"]},

            "wage_source": {"type": "string"},

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

      "inferred_roles": {

        "type": "array",

        "minItems": 1,

        "items": {

          "type": "object",

          "additionalProperties": False,

          "properties": {

            "role_title": {"type": "string"},
            "annual_wage": {"type": ["number", "null"]},
            "wage_source": {"type": "string"},
            "months_until_hire": {"type": ["number", "null"]},
            "notes": {"type": "string"},
          },
          "required": ["role_title", "annual_wage", "wage_source", "months_until_hire", "notes"],
        },
      },
      "inferred_roles_summary": {"type": "string"},

      "business_naics_6": {"type": ["string", "null"]},

      "confidence": {"type": "number"},

    }



  if consult_type_norm == "financials_year1":

    return {

      "unit_cadence": {"type": "string", "enum": ["weekly", "monthly", "contract"]},

      "unit_price": {"type": "number"},

      "units_per_week_capacity": {"type": "number"},

      "units_per_period_capacity": {"type": "number"},

      "avg_units_per_week_year1": {"type": "number"},

      "avg_units_per_period_year1": {"type": "number"},

      "operating_weeks_per_year": {"type": "number"},

      "operating_periods_per_year": {"type": "number"},

      "utilization_rate": {"type": "number"},

      "product_overrides": {"type": "object"},

    }



  if consult_type_norm == "financials":

    return {

      "financials_summary": {"type": "string"},

      "current_revenue": {"type": "number"},

      "current_cogs": {"type": "number"},

      "marketing_total_year1": {"type": "number"},

      "marketing_percent_of_revenue": {"type": "number"},

      "other_operating_expense": {"type": "number"},

      "monthly_rent_expense": {"type": "number"},

      "future_rent_expected": {"type": "boolean"},

      "other_monthly_debt_payments": {"type": "number"},

      "current_payroll": {"type": "number"},

      "current_num_employees": {"type": "number"},

      "current_capex": {"type": "number"},

      "ar_balance": {"type": "number"},

      "ap_balance": {"type": "number"},

      "inventory_balance": {"type": "number"},

      "initial_assets": {"type": "number"},

      "initial_lease": {"type": "number"},

      "initial_equity": {"type": "number"},

      "total_debt_outstanding": {"type": "number"},

      "annual_interest_payment": {"type": "number"},

      "annual_principal_payment": {"type": "number"},

      "owner_compensation": {"type": "number"},

      "cash_on_hand": {"type": "number"},

      "cash_strategy": {"type": "string", "enum": ["preserve_cash", "shareholder_return", "balanced"]},

      "funding_preference": {"type": "string", "enum": ["debt", "equity", "both"]},

      "funding_split_debt_share": {"type": "number", "enum": [0.7, 0.5, 0.3]},

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

  match = re.search(r"('P<num>\d+(':\.\d+)')\s*('P<suffix>[kmb])'", cleaned)

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


def _confirm_clarify_message(
  field: str,
  *,
  consult_type: str | None = None,
  baseline_json: Any = None,
) -> str:

  # Field-specific clarification prompts are safer than the generic "single number"
  # prompt for structured fields like income_intent (which expects min+max).
  field_norm = str(field or "").strip().lower()
  if field_norm.endswith("gender_age_intent"):
    return (
      "Just to confirm, please provide a target formatted like this for example: "
      "\"18 to 55\""
    )
  if field_norm.endswith("income_intent"):
    return (
      "Just to confirm, please provide an income range formatted like this for example: "
      "60000 to 120000"
    )
  if field_norm.endswith("cash_strategy"):
    return (
      "Just to confirm, which is closer to what you want for extra cash: Reinvest, Preserve cash, Shareholder return, or Balanced?"
    )
  if field_norm.endswith("units_per_week_capacity") or field_norm.endswith("units_per_period_capacity"):
    cadence = ""
    unit_name = ""
    try:
      # baseline_json is typically the consult's canonical baseline. For unified consults,
      # ops facts may be nested or the prompt may be asking about an ops.* field.
      base = baseline_json if isinstance(baseline_json, dict) else {}
      if isinstance(base, dict) and (
        str(consult_type or "").strip().lower() == "unified" or field_norm.startswith("ops.")
      ):
        ops_base = base.get("ops")
        if isinstance(ops_base, dict):
          base = ops_base
      if isinstance(base, dict):
        cadence = str(base.get("unit_cadence") or "").strip().lower()
        unit_name = str(base.get("unit_name") or "").strip()
    except Exception:
      cadence = ""
      unit_name = ""

    # Default to a generic prompt that avoids internal field names and makes the period explicit.
    period_label = "period"
    if cadence == "weekly":
      period_label = "week"
    elif cadence in ("monthly", "contract"):
      period_label = "month"

    unit_phrase = unit_name or "units"
    # Avoid confusing the user with internal field jargon ("units_per_week_capacity").
    return (
      f"Just to confirm your capacity: in a fully booked {period_label}, about how many {unit_phrase} can you handle? "
      "(One number is fine, e.g., 20.)"
    )

  return (
    f"Just to confirm, what should we record for {_humanize_patch_field(field)}? "
    "A short answer in your own words is fine."
  )


def _ops_interview_field_allowed(field: str, ops_interview_filter: Dict[str, Any] | None) -> bool:
  """During an active Ops interview turn, only ops/business/fulfillment fields may be
  patched, and milestones only during the explicit milestone-capture step.

  This is the ops-side analogue of the financials stage patch_targets narrowing: it
  stops the model from routing a normal interview answer (e.g. a utilization figure)
  into an unrelated downstream field such as financials.future_rent_expected or
  ops.milestones, whose type mismatch would otherwise surface a fallback clarifier.
  """
  if not isinstance(ops_interview_filter, dict) or not ops_interview_filter.get("enabled"):
    return True
  raw = str(field or "").strip()
  group, dot, tail = raw.partition(".")
  if not dot:
    group, tail = "ops", raw
  group = group.strip().lower()
  tail = tail.strip()
  if group not in ("ops", "business", "fulfillment"):
    return False
  if tail == "milestones" and not ops_interview_filter.get("allow_milestones"):
    return False
  # Model-owned meta/structure fields: the consultant GPT authors these
  # in its own patches; a client interview answer never legitimately
  # sets them through the router. Routing one there (e.g. "I insist on
  # 70%" -> confidence) hits a type gate no conversational answer can
  # satisfy and loops the fallback clarifier.
  if tail in ("confidence", "lob_models"):
    return False
  return True


def _parse_compact_number_token(raw: str) -> Optional[float]:

  """

  Parse common compact numeric formats used by clients:

  - 60000
  - 60,000
  - 60k / 60 K
  - 1.2m

  Returns a float (to match "number" schema usage) or None.

  """

  text = str(raw or "").strip().lower()
  if not text:
    return None

  # Strip common decorations.
  text = text.replace("$", "").replace(",", "").strip()

  m = re.match(r"^(\d+(?:\.\d+)?)\s*([km])?$", text)
  if not m:
    return None

  try:
    base = float(m.group(1))
  except Exception:
    return None

  suffix = (m.group(2) or "").strip().lower()
  if suffix == "k":
    base *= 1000.0
  elif suffix == "m":
    base *= 1000000.0

  return base


def _extract_compact_numbers(text: str) -> List[float]:

  # Extract ordered numbers like 60k, 120000, 1.2m from a blob of text.
  blob = str(text or "")
  blob = blob.replace("–", "-").replace("—", "-")
  # Keep commas for token-level parsing; we remove them in the token parser.
  tokens = re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*[kmKM]?", blob)
  out: List[float] = []
  for tok in tokens:
    val = _parse_compact_number_token(tok)
    if val is None:
      continue
    out.append(val)
  return out


def _parse_income_range_from_text(text: str) -> Optional[Tuple[float, float]]:

  """

  Deterministically parse user text into (income_min, income_max).

  Supports:

  - "60k to 120k" / "$60,000-$120,000"
  - "$60,000–$120,000 per year"
  - "60k and up" => (60000, default_max)
  - "under 120k" => (0, 120000)

  This is intentionally conservative: if we cannot confidently parse, return None.

  """

  raw = str(text or "").strip()
  if not raw:
    return None

  norm = raw.lower()
  norm = norm.replace("–", "-").replace("—", "-")

  nums = _extract_compact_numbers(norm)
  if not nums:
    return None

  DEFAULT_MAX = 1000000.0

  # Open-ended upper range: "60k and up", "60k+", "at least 60k", etc.
  if re.search(r"\b(and\s+up|or\s+more|and\s+above|at\s+least|minimum)\b", norm) or "+" in norm:
    mn = float(nums[0])
    mx = float(max(DEFAULT_MAX, mn))
    return mn, mx

  # Open-ended lower range: "under 120k", "up to 120k", "below 120k", etc.
  if re.search(r"\b(under|below|up\s*to|less\s+than|at\s+most|maximum|max)\b", norm):
    mx = float(nums[0])
    mn = 0.0
    if mx < mn:
      return None
    return mn, mx

  # Two-number range.
  if len(nums) >= 2:
    a = float(nums[0])
    b = float(nums[1])
    mn = float(min(a, b))
    mx = float(max(a, b))
    return mn, mx

  # Single number with no clear open-ended semantics is ambiguous (e.g., "60k").
  return None


def _parse_gender_focus_from_text(text: str) -> Optional[str]:

  norm = str(text or "").strip().lower()
  if not norm:
    return None

  # Normalize common typos.
  norm = norm.replace("woment", "women")

  has_male = bool(re.search(r"\b(male|men|man|boys|guys)\b", norm))
  has_female = bool(re.search(r"\b(female|women|woman|girls|ladies)\b", norm))
  has_all = bool(re.search(r"\b(all|everyone|anyone)\b", norm))
  has_mix = bool(re.search(r"\b(mix|mixed|both)\b", norm))

  if has_all or has_mix or (has_male and has_female):
    return "all"
  if has_male:
    return "male"
  if has_female:
    return "female"
  return None


def _parse_age_range_from_text(text: str) -> Optional[Tuple[float, float]]:

  raw = str(text or "").strip().lower()
  if not raw:
    return None
  norm = raw.replace("–", "-").replace("—", "-")

  # Explicit ranges: "18-55", "18 to 55".
  m = re.search(r"\b(\d{1,3})\s*(?:-|to)\s*(\d{1,3})\b", norm)
  if m:
    a = float(m.group(1))
    b = float(m.group(2))
    mn = float(min(a, b))
    mx = float(max(a, b))
    if 0 <= mn <= mx <= 120:
      return mn, mx
    return None

  # Open-ended: "18+", "18 and up".
  m = re.search(r"\b(\d{1,3})\s*\+", norm) or re.search(
    r"\b(\d{1,3})\s*(?:and\s+up|and\s+older|plus)\b", norm
  )
  if m:
    mn = float(m.group(1))
    mx = 120.0
    if 0 <= mn <= mx <= 120:
      return mn, mx
    return None

  # Upper-bounded: "under 55", "up to 55".
  m = re.search(r"\b(under|below|up\s*to|at\s*most|max(?:imum)?)\s*(\d{1,3})\b", norm)
  if m:
    mx = float(m.group(2))
    mn = 0.0
    if 0 <= mn <= mx <= 120:
      return mn, mx
    return None

  return None


def _maybe_parse_gender_age_intent_value_json(
  *, field: str, value_json_raw: str, allowed_types: List[str]
) -> Tuple[bool, Any]:

  field_norm = str(field or "").strip().lower()
  if not field_norm.endswith("gender_age_intent"):
    return False, None
  if "array" not in [str(t).strip().lower() for t in (allowed_types or [])]:
    return False, None

  gender_focus = _parse_gender_focus_from_text(value_json_raw)
  age_range = _parse_age_range_from_text(value_json_raw)
  if not gender_focus or not age_range:
    return False, None

  age_min, age_max = age_range
  return True, [{"gender_focus": gender_focus, "age_min": float(age_min), "age_max": float(age_max)}]


def _maybe_normalize_structured_array_value(
  *, field: str, value: Any, allowed_types: List[str]
) -> Tuple[bool, Any]:

  """

  Some model outputs serialize the right content but with the wrong top-level
  container (e.g., object instead of array). For a small set of structured
  fields, normalize the container deterministically so we don't fall into
  confirm_clarify loops.

  This does not guess intent; it only reshapes already-provided values.

  """

  field_norm = str(field or "").strip().lower()
  allowed_norm = [str(t).strip().lower() for t in (allowed_types or [])]
  if "array" not in allowed_norm:
    return False, None

  def _to_num(x: Any) -> Optional[float]:
    try:
      if x is None:
        return None
      return float(x)
    except Exception:
      return None

  if field_norm.endswith("income_intent"):
    if isinstance(value, dict):
      mn = _to_num(value.get("income_min"))
      mx = _to_num(value.get("income_max"))
      if mn is None or mx is None:
        return False, None
      if mx < mn:
        return False, None
      return True, [{"income_min": float(mn), "income_max": float(mx)}]
    return False, None

  if field_norm.endswith("gender_age_intent"):
    if isinstance(value, dict):
      gf_raw = str(value.get("gender_focus") or "").strip().lower()
      gf_map = {
        "all": "all",
        "any": "all",
        "both": "all",
        "mixed": "all",
        "men": "male",
        "male": "male",
        "women": "female",
        "woman": "female",
        "female": "female",
      }
      gf = gf_map.get(gf_raw, gf_raw)
      if gf not in ("female", "male", "all"):
        return False, None
      mn = _to_num(value.get("age_min"))
      mx = _to_num(value.get("age_max"))
      if mn is None or mx is None:
        return False, None
      if mx < mn:
        return False, None
      return True, [{"gender_focus": gf, "age_min": float(mn), "age_max": float(mx)}]
    return False, None

  return False, None


def _maybe_parse_income_intent_value_json(
  *, field: str, value_json_raw: str, allowed_types: List[str]
) -> Tuple[bool, Any]:

  # Only handle the target-market income intent field (array of {income_min, income_max}).
  field_norm = str(field or "").strip().lower()
  if not field_norm.endswith("income_intent"):
    return False, None
  if "array" not in [str(t).strip().lower() for t in (allowed_types or [])]:
    return False, None

  parsed = _parse_income_range_from_text(value_json_raw)
  if not parsed:
    return False, None

  mn, mx = parsed
  if mx < mn:
    return False, None

  return True, [{"income_min": float(mn), "income_max": float(mx)}]


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

  ops_interview_filter: Dict[str, Any] | None = None,

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

  if consult_type_norm not in ("ops", "target_market", "people", "financials", "financials_year1", "unified"):

    raise ValueError(f"Unknown consult_type={consult_type!r}")



  api_key = _require_openai_key()

  model = _openai_model()



  confirm_questions = {

    "ops": "Does this look right before we move on to Customers & Positioning'",

    "target_market": "Does this look right before we move on to People & Capability'",

    "people": "Does this look right before we move on to Financials'",

    "financials": "Does this look right before we move on to Submit intake'",

    "financials_year1": "Does this look right before we move on'",

    "unified": "Does this look right before we move on'",

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

      "unit_cadence",

      "units_per_week_capacity",

      "units_per_period_capacity",

      "operating_periods_per_year",

      "unit_price",

      "shipping_method",

      "sales_modality",

      "geographic_scope",
      "geographic_coverage",
      "countries",
      "competitive_advantage",
      "milestones",
      "capacity_driver",
      "primary_growth_lever",

      "legal_entity",

      "lob_models",

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

      "marketing_plan_summary",

    ],

    "people": [
      "people",
      "inferred_roles",
      "rest_of_team_payroll_year1",
    ],
    "financials": [

      "current_revenue",

      "current_cogs",
      "cogs_total_year1",
      "cogs_percent_of_revenue",

      "marketing_total_year1",

      "marketing_percent_of_revenue",

      "other_operating_expense",

      "monthly_rent_expense",

      "future_rent_expected",

      "other_monthly_debt_payments",

      "current_payroll",
      "payroll_total_year1",

      "current_num_employees",

      "current_capex",

      "ar_balance",

      "ap_balance",

      "inventory_balance",

      "initial_assets",

      "initial_lease",

      "initial_equity",

      "total_debt_outstanding",

      "annual_interest_payment",

      "annual_principal_payment",

      "owner_compensation",

      "cash_on_hand",

      "cash_strategy",

      "funding_preference",

      "funding_split_debt_share",

    ],

    "financials_year1": [

      "unit_cadence",

      "unit_price",

      "units_per_week_capacity",

      "units_per_period_capacity",

      "avg_units_per_week_year1",

      "avg_units_per_period_year1",

      "operating_weeks_per_year",

      "operating_periods_per_year",

      "utilization_rate",

      "product_overrides",

    ],

    "unified": [

      "business.name",

      "business.address",

      "business.start_date",

      "business.address_street",

      "business.address_city",

      "business.address_state",

      "business.address_zip",

      "business.address_country",

      *[f"ops.{f}" for f in _value_schema_by_consult_field(consult_type="ops").keys()],

      *[f"market.{f}" for f in _value_schema_by_consult_field(consult_type="target_market").keys()],

      *[f"people.{f}" for f in _value_schema_by_consult_field(consult_type="people").keys()],
      *[f"financials.{f}" for f in _value_schema_by_consult_field(consult_type="financials").keys()],

      *[f"fulfillment.{f}" for f in _value_schema_by_consult_field(consult_type="fulfillment").keys()],

      # Coherence lever fields exist ONLY while the coherence question
      # is live (the frame is present). Statically allowing
      # ops.product_overrides let the ops-interview router hallucinate
      # it from a normal answer and loop the object-type clarifier —
      # the exact malformed-clarifier class, reintroduced for one run.
      *(
        ["coherence.option", "coherence.parked", "ops.product_overrides"]
        if isinstance((shared_context or {}).get("coherence_controller"), dict)
        else []
      ),

    ],

  }[consult_type_norm]



  recent_messages_list = list(recent_messages or [])

  last_assistant = _last_assistant_message(recent_messages_list)



  extra_instructions = ""

  if consult_type_norm == "financials_year1":
    extra_instructions = (
      "Financials Year 1 revenue edits:\n"
      "- If the user references a specific product name, return patch field "
      "\"product_overrides\" with an object mapping that product name to its updated driver values.\n"
      "- If the user does not specify a product, apply the update to the global driver field "
      "(unit_cadence, unit_price, units_per_week_capacity, units_per_period_capacity, avg_units_per_week_year1, avg_units_per_period_year1, operating_weeks_per_year, operating_periods_per_year, utilization_rate).\n"
      "- If the last assistant message presented labeled revenue options (for example Option 1 / Option 2 / Option 3) and the user selects one by number, label, or short description, infer the corresponding revenue-driver patch from that option and return edit_patch.\n"
      "- Use the last assistant message as the source of truth for what each option changes; do not require the user to restate the numbers.\n"
      "- If the assistant already accepted the current revenue setup and moved on to a different financial question, do not invent a revenue edit unless the user explicitly asks to change revenue drivers.\n"
    )

  if consult_type_norm == "financials" or (
    consult_type_norm == "unified" and str(active_focus or "").strip().lower() == "financials"
  ):
    extra_instructions = (
      extra_instructions
      + "Financials stage inference:\n"
      + "- Use shared_context.financials_controller.current_stage as the source of truth for the active financial stage.\n"
      + "- If patch_targets is present there, prefer those field(s) when translating the user's reply into a patch.\n"
      + "- If shared_context.financials_controller.current_stage.allowed_values is present, treat that list as the exact persisted values allowed for the active stage.\n"
      + "- If shared_context.financials_controller.current_stage.name is cash_strategy, use shared_context.financials_controller.current_stage.options to map the user's preference to one allowed value.\n"
      + "- If current_stage.name is cash_strategy and current_stage.decision_mode is initial: if the user's preference is clear, return edit_patch; if it is ambiguous, return confirm_clarify with one short closed question.\n"
      + "- If current_stage.name is cash_strategy and current_stage.decision_mode is clarify: if the user's intent is clear enough, return edit_patch; if it is still ambiguous, return confirm_clarify that asks the user to choose one of the listed options directly.\n"
      + "- If current_stage.name is cash_strategy and current_stage.decision_mode is forced_choice: do not return confirm_proceed; infer the selected option from the user's reply, nearby context, and any numbered choice in the last assistant message, then return edit_patch.\n"
      + "- If current_stage.name is cash_strategy and current_stage.decision_mode is forced_choice and the user is still indirect, choose the single best-fit allowed value from context and return edit_patch so the stage can persist.\n"
      + "- If the active financial stage presented a baseline and the user briefly agrees, return confirm_proceed.\n"
      + "- If the user gives a concrete replacement for the active financial stage, return edit_patch for the narrow stage field(s) only.\n"
      + "- If the user gives directionally clear intent but one concrete number or boolean is still missing for the active stage, return confirm_clarify with one short question for that missing fact.\n"
      + "Financials revenue handling:\n"
      + "- If the last assistant message is asking how much revenue the business is bringing in and the user answers nothing, none yet, no revenue, or basically nothing, return edit_patch with current_revenue = 0.\n"
      + "- If the user gives a monthly revenue figure for that question, convert it to an annual amount before patching current_revenue.\n"
      + "Financials owner compensation handling:\n"
      + "- The owner_compensation field is MONTHLY. If the last assistant message asked about owner compensation per month and the user answers with an annual figure (per year, a year, annually - any phrasing meaning yearly), divide by 12 before patching owner_compensation. A monthly answer patches as-is.\n"
      + "Financials rent handling:\n"
      + "- If the last assistant message is asking about current rent for business space, interpret replies like no, none, work from home, home-based, remote, no dedicated space, or not paying for space as a change to monthly_rent_expense = 0.\n"
      + "- If the last assistant message is asking whether paid dedicated business space is expected later, interpret clear yes/no style answers as a boolean patch for future_rent_expected rather than confirm_proceed.\n"
      + "- If the last assistant message is asking about leased equipment or space beyond main rent, interpret clear no/none style answers as initial_lease = 0 and interpret amount answers as the monthly lease amount.\n"
      + "Financials funding handling:\n"
      + "- If current_stage.name is funding_preference, map answers like loans, borrowing, bank financing, a line of credit, or leverage to funding_preference = debt; answers like investors, my own money, savings, no loans, or don't want debt to funding_preference = equity; and answers like a mix, a combination, some of each, or both to funding_preference = both. Return edit_patch when the preference is clear; return confirm_clarify with one short question if it is genuinely ambiguous.\n"
      + "- If current_stage.name is funding_split_debt_share, map answers like mostly debt, mainly loans, 70/30, or 70 percent debt to funding_split_debt_share = 0.7; even, half and half, or 50/50 to 0.5; and mostly equity, mainly investors, or 30/70 to 0.3. Interpret X/Y style answers as debt share first (X is debt). Return edit_patch with the closest allowed value.\n"
    )

  if consult_type_norm == "people" or (
    consult_type_norm == "unified" and str(active_focus or "").strip().lower() == "people"
  ):
    extra_instructions = (
      extra_instructions
      + "People edits:\n"
      "- The user may update wages or timing for either key people or suggested roles.\n"
      "- If the user references a specific person (name or title), update the matching entry in people.\n"
      "- If the user references a suggested role, update the matching entry in inferred_roles.\n"
      "- When updating a wage, set wage_source to \"client_override\" for that entry.\n"
      "- When updating timing, set months_until_hire for that inferred role.\n"
      "- Return the full updated list for the field you change (people or inferred_roles).\n"
      "- If it is unclear which entry the user meant, return confirm_clarify with one short question.\n"
      "Rest-of-team payroll handling (takes precedence over continue_chat):\n"
      "- If shared_context.people_controller.current_question is rest_of_team_payroll, the app just asked for the total payroll of everyone beyond the owner and key people. A direct answer to that question is NOT continue_chat - translate it into edit_patch on the field named in people_controller.patch_targets (people.rest_of_team_payroll_year1 when fields are group-scoped, rest_of_team_payroll_year1 otherwise).\n"
      "- Interpret INTENT, not exact wording: any reply that means there are no additional employees (for example no one else, just us, nobody, none, it's only me - including misspellings or informal phrasing) means rest_of_team_payroll_year1 = 0.\n"
      "- If the user gives a monthly figure for that question, convert it to an annual amount before patching.\n"
      "- If the user gives a range, use a single representative number near the middle.\n"
      "- If the user later says that rest-of-team total is wrong, treat the correction as an edit_patch on rest_of_team_payroll_year1.\n"
    )

  if isinstance((shared_context or {}).get("coherence_controller"), dict):
    extra_instructions = (
      extra_instructions
      + "Coherence lever handling (takes precedence over continue_chat and confirm_proceed):\n"
      "- shared_context.coherence_controller means the app just asked the client to choose how to close a viability gap. The offered options (ids, labels, exact numbers) are in coherence_controller.options.\n"
      "- If the client picks an option by number, label, rough description, or brief agreement (yes, go ahead, do that, the suggested one - including misspellings and informal phrasing), return edit_patch with field coherence.option set to that option's id. Brief agreement means the option marked recommended/suggested.\n"
      "- If the client gives their own concrete prices for named products, return edit_patch with ops.product_overrides mapping each product name to an object with unit_price. Do not refuse prices outside the mentioned range - the app clamps them safely.\n"
      "- If the client gives a concrete dollar amount for a cost the question covered (marketing, rent, payroll, overhead), return edit_patch on the matching field from coherence_controller.patch_targets. Respect each field's own basis: monthly_rent_expense and other_operating_expense are MONTHLY; marketing_total_year1, payroll_total_year1, current_payroll are ANNUAL - convert if the client spoke in the other basis.\n"
      "- If the client wants to KEEP their current values for what this question offered and move on (keep prices as they are, no changes to that, we're fine as-is - any phrasing meaning they decline this particular lever), return edit_patch with coherence.option = \"decline\". Declining one lever is a normal, respected answer - do not re-ask.\n"
      "- If the client wants to pause, defer, come back later, or stop for now (any phrasing that means that), return edit_patch with coherence.parked = true. Never pressure them to continue.\n"
      "- If the client asks a question about the numbers themselves, answer_readonly is appropriate.\n"
      "- Interpret INTENT, not exact wording; never require specific phrases.\n"
    )


  system = f"""

You are the intent router for a multi-step business intake app.



Non-negotiable rule:

- You are the SOLE authority for interpreting the user's intent. Do NOT defer intent decisions to any frontend/back-end heuristics.

Client-facing wording:

- Never use the phrase "Year 1" or "Year-1" in assistant_message, even when confirming a value the user described that way. Say it naturally instead: "the year ahead", "the first 12 months", "annually", or "a year".



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

  - If confirm_question is present and the user response is a brief acknowledgement with no new facts or correction request, return confirm_proceed.

2) confirm_clarify

  - Use when the user message is ambiguous/contradictory/uncertain and you cannot confidently infer whether they want changes or want to proceed.

  - assistant_message MUST be a single, brief clarifying question.

  - Do NOT repeat, paraphrase, or re-summarize any prior summary content.

3) edit_patch

  - Use when the user is requesting a correction/update to ANY already-captured fact in the canonical intake model (even if phrased casually), regardless of what stage the consult is currently in.

  - IMPORTANT: If the last assistant message PROPOSED a specific change to one or more facts (e.g., "Should we update X to 700'")

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

- If confirm_question is present and the user response is a brief acknowledgement with no corrections or new facts, you MUST return confirm_proceed (do not restate the summary).

- If the last assistant message described the fulfillment model (who performs it + typical timing) and the user agrees, set fulfillment.personnel and fulfillment.time accordingly.



{extra_instructions}



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

    raise RuntimeError(_format_openai_error(resp))



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
          # Don't hard-fail the entire intake if the model emits a malformed edit_patch.
          # Instead, ask the user to clarify/rephrase so we can try again next turn.
          result["action"] = "confirm_clarify"
          result["assistant_message"] = (
            "I had trouble applying that change. Can you rephrase what you want to update?"
          )
          result["patch"] = None
          return result



        value_schemas = _value_schema_by_consult_field(consult_type=consult_type_norm)

        patch_dict: Dict[str, Any] = {}

        for op in patch_ops:

          if not isinstance(op, dict):

            continue

          field = str(op.get("field") or "").strip()

          value_json_raw = str(op.get("value_json") or "").strip()

          if not field:

            continue

          if not _ops_interview_field_allowed(field, ops_interview_filter):
            # Hallucinated out-of-scope patch during the ops interview: drop the
            # item instead of type-checking it into a fallback clarifier.
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
            ok_income, income_val = _maybe_parse_income_intent_value_json(
              field=field,
              value_json_raw=value_json_raw,
              allowed_types=allowed_types,
            )
            if ok_income:
              ok = True
              value = income_val

          if not ok:
            ok_ga, ga_val = _maybe_parse_gender_age_intent_value_json(
              field=field,
              value_json_raw=value_json_raw,
              allowed_types=allowed_types,
            )
            if ok_ga:
              ok = True
              value = ga_val

          # Normalize container shapes (e.g., object -> single-item array) for a few
          # structured array fields to avoid confirm_clarify loops.
          ok_norm, norm_val = _maybe_normalize_structured_array_value(
            field=field,
            value=value,
            allowed_types=allowed_types,
          )
          if ok_norm:
            value = norm_val

          if not ok:

            return {

              "action": "confirm_clarify",

              "assistant_message": _confirm_clarify_message(
                field,
                consult_type=consult_type_norm,
                baseline_json=baseline_json,
              ),
              "patch": None,

            }



          if allowed_types:

            if value is None:

              if "null" not in allowed_types:

                return {

                  "action": "confirm_clarify",

                  "assistant_message": _confirm_clarify_message(
                    field,
                    consult_type=consult_type_norm,
                    baseline_json=baseline_json,
                  ),
                  "patch": None,

                }

            elif isinstance(value, bool):

              if "boolean" not in allowed_types:

                return {

                  "action": "confirm_clarify",

                  "assistant_message": _confirm_clarify_message(
                    field,
                    consult_type=consult_type_norm,
                    baseline_json=baseline_json,
                  ),
                  "patch": None,

                }

            elif isinstance(value, (int, float)) and not isinstance(value, bool):

              if "number" not in allowed_types:

                return {

                  "action": "confirm_clarify",

                  "assistant_message": _confirm_clarify_message(
                    field,
                    consult_type=consult_type_norm,
                    baseline_json=baseline_json,
                  ),
                  "patch": None,

                }

            elif isinstance(value, str):

              if "string" not in allowed_types:

                return {

                  "action": "confirm_clarify",

                  "assistant_message": _confirm_clarify_message(
                    field,
                    consult_type=consult_type_norm,
                    baseline_json=baseline_json,
                  ),
                  "patch": None,

                }

            elif isinstance(value, list):

              if "array" not in allowed_types:

                return {

                  "action": "confirm_clarify",

                  "assistant_message": _confirm_clarify_message(
                    field,
                    consult_type=consult_type_norm,
                    baseline_json=baseline_json,
                  ),
                  "patch": None,

                }

            elif isinstance(value, dict):

              if "object" not in allowed_types:

                return {

                  "action": "confirm_clarify",

                  "assistant_message": _confirm_clarify_message(
                    field,
                    consult_type=consult_type_norm,
                    baseline_json=baseline_json,
                  ),
                  "patch": None,

                }



          patch_dict[field] = value

        if not patch_dict:
          # Every patch item was dropped as out-of-scope: treat the message as a
          # normal answer for the active consult instead of a correction.
          result["action"] = "continue_chat"
          result["assistant_message"] = ""
          result["patch"] = None
          return result

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
    # Don't hard-fail the entire intake if the model emits a malformed edit_patch.
    # Instead, ask the user to clarify/rephrase so we can try again next turn.
    parsed["action"] = "confirm_clarify"
    parsed["assistant_message"] = (
      "I had trouble applying that change. Can you rephrase what you want to update?"
    )
    parsed["patch"] = None
    return parsed

  value_schemas = _value_schema_by_consult_field(consult_type=consult_type_norm)

  patch_dict: Dict[str, Any] = {}

  for op in patch_ops:

    if not isinstance(op, dict):

      continue

    field = str(op.get("field") or "").strip()

    value_json_raw = str(op.get("value_json") or "").strip()

    if not field:

      continue

    if not _ops_interview_field_allowed(field, ops_interview_filter):
      # Hallucinated out-of-scope patch during the ops interview: drop the
      # item instead of type-checking it into a fallback clarifier.
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
      ok_income, income_val = _maybe_parse_income_intent_value_json(
        field=field,
        value_json_raw=value_json_raw,
        allowed_types=allowed_types,
      )
      if ok_income:
        ok = True
        value = income_val

    if not ok:
      ok_ga, ga_val = _maybe_parse_gender_age_intent_value_json(
        field=field,
        value_json_raw=value_json_raw,
        allowed_types=allowed_types,
      )
      if ok_ga:
        ok = True
        value = ga_val

    ok_norm, norm_val = _maybe_normalize_structured_array_value(
      field=field,
      value=value,
      allowed_types=allowed_types,
    )
    if ok_norm:
      value = norm_val

    if not ok:

      parsed["action"] = "confirm_clarify"

      parsed["assistant_message"] = (

        _confirm_clarify_message(
          field,
          consult_type=consult_type_norm,
          baseline_json=baseline_json,
        )
      )

      parsed["patch"] = None

      return parsed



    if allowed_types:

      if value is None:

        if "null" not in allowed_types:

          parsed["action"] = "confirm_clarify"

          parsed["assistant_message"] = (

            _confirm_clarify_message(
              field,
              consult_type=consult_type_norm,
              baseline_json=baseline_json,
            )
          )

          parsed["patch"] = None

          return parsed

      elif isinstance(value, bool):

        if "boolean" not in allowed_types:

          parsed["action"] = "confirm_clarify"

          parsed["assistant_message"] = (

            _confirm_clarify_message(
              field,
              consult_type=consult_type_norm,
              baseline_json=baseline_json,
            )
          )

          parsed["patch"] = None

          return parsed

      elif isinstance(value, (int, float)) and not isinstance(value, bool):

        if "number" not in allowed_types:

          parsed["action"] = "confirm_clarify"

          parsed["assistant_message"] = (

            _confirm_clarify_message(
              field,
              consult_type=consult_type_norm,
              baseline_json=baseline_json,
            )
          )

          parsed["patch"] = None

          return parsed

      elif isinstance(value, str):

        if "string" not in allowed_types:

          parsed["action"] = "confirm_clarify"

          parsed["assistant_message"] = (

            _confirm_clarify_message(
              field,
              consult_type=consult_type_norm,
              baseline_json=baseline_json,
            )
          )

          parsed["patch"] = None

          return parsed

      elif isinstance(value, list):

        if "array" not in allowed_types:

          parsed["action"] = "confirm_clarify"

          parsed["assistant_message"] = (

            _confirm_clarify_message(
              field,
              consult_type=consult_type_norm,
              baseline_json=baseline_json,
            )
          )

          parsed["patch"] = None

          return parsed

      elif isinstance(value, dict):

        if "object" not in allowed_types:

          parsed["action"] = "confirm_clarify"

          parsed["assistant_message"] = (

            _confirm_clarify_message(
              field,
              consult_type=consult_type_norm,
              baseline_json=baseline_json,
            )
          )

          parsed["patch"] = None

          return parsed



    patch_dict[field] = value

  if not patch_dict:
    # Every patch item was dropped as out-of-scope: treat the message as a
    # normal answer for the active consult instead of a correction.
    parsed["action"] = "continue_chat"
    parsed["assistant_message"] = ""
    parsed["patch"] = None
    return parsed

  parsed["patch"] = patch_dict

  return parsed
