from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify

from intake_consult_draft import append_messages, create_draft, get_draft, update_draft
from intake_submission import get_mysql_connection

from .system_prompt import SYSTEM_PROMPT


MODEL_COLUMNS: Tuple[str, ...] = (
  "operating_model_json",
  "operating_structure_json",
  "customer_model_json",
  "fulfillment_model_json",
  "revenue_model_json",
  "cogs_model_json",
  "gna_model_json",
  "marketing_model_json",
  "headcount_model_json",
  "people_json",
  "milestones_model_json",
  "target_market_json",
)

MAX_FORCE_PATCH_ATTEMPTS = 3
MAX_CONVERSATION_ATTEMPTS = 5

MODEL_ORDER: Tuple[str, ...] = (
  "operating_model_json",
  "operating_structure_json",
  "customer_model_json",
  "fulfillment_model_json",
  "revenue_model_json",
  "cogs_model_json",
  "gna_model_json",
  "marketing_model_json",
  "headcount_model_json",
  "people_json",
  "milestones_model_json",
  "target_market_json",
)

FIELD_PLAN: Dict[str, List[Dict[str, Any]]] = {
  "operating_model_json": [
    {
      "key": "business_type",
      "prompt": "Briefly describe what your business does day to day and how it makes money.",
      "requires_confirmation": True,
      "special": "business_type",
    },
    {
      "key": "start_date",
      "prompt": "What is the planned or actual start date for the business?",
      "requires_confirmation": False,
      "special": "date",
    },
    {
      "key": "consumer_type",
      "prompt": "Who do you primarily serve?",
      "requires_confirmation": False,
    },
    {
      "key": "unit_name",
      "prompt": "What is the primary unit you sell or deliver?",
      "requires_confirmation": False,
    },
    {
      "key": "unit_description",
      "prompt": "In one sentence, describe what a single unit includes.",
      "requires_confirmation": False,
    },
    {
      "key": "sales_modality",
      "prompt": "What is your primary sales modality?",
      "requires_confirmation": False,
      "special": "sales_modality",
    },
    {
      "key": "shipping_method",
      "prompt": "What is the primary delivery or shipping method?",
      "requires_confirmation": False,
    },
    {
      "key": "geographic_scope",
      "prompt": "What is your geographic scope?",
      "requires_confirmation": False,
      "special": "geographic_scope",
    },
    {
      "key": "geographic_coverage",
      "prompt": "Which areas do you cover?",
      "requires_confirmation": False,
    },
    {
      "key": "countries",
      "prompt": "Which countries do you serve?",
      "requires_confirmation": False,
    },
    {
      "key": "legal_entity",
      "prompt": "What is your legal entity type?",
      "requires_confirmation": False,
      "special": "legal_entity",
    },
    {
      "key": "capacity_driver",
      "prompt": "What most limits your capacity today?",
      "requires_confirmation": False,
      "special": "capacity_driver",
    },
    {
      "key": "primary_growth_lever",
      "prompt": "What is your primary lever for growth?",
      "requires_confirmation": False,
    },
  ],
  "operating_structure_json": [
    {
      "key": "operating_unit",
      "prompt": "What is the core operating unit of work?",
      "requires_confirmation": False,
    },
    {
      "key": "process_overview",
      "prompt": "Give a brief, plain-English overview of the main operating process end-to-end.",
      "requires_confirmation": False,
    },
    {
      "key": "primary_constraint",
      "prompt": "What is the single biggest constraint in operations today?",
      "requires_confirmation": False,
    },
  ],
  "customer_model_json": [
    {
      "key": "primary_customer",
      "prompt": "Who is the primary customer you serve?",
      "requires_confirmation": False,
    },
    {
      "key": "customer_problem",
      "prompt": "What is the main problem or need you solve for them?",
      "requires_confirmation": False,
    },
    {
      "key": "purchase_decision",
      "prompt": "What usually drives their purchase decision?",
      "requires_confirmation": False,
    },
  ],
  "fulfillment_model_json": [
    {
      "key": "fulfillment_model",
      "prompt": "How is fulfillment handled?",
      "requires_confirmation": False,
    },
    {
      "key": "who_fulfills",
      "prompt": "Who performs the fulfillment work?",
      "requires_confirmation": False,
    },
    {
      "key": "lead_time",
      "prompt": "What is the typical lead time from order to delivery?",
      "requires_confirmation": False,
    },
  ],
  "revenue_model_json": [
    {
      "key": "units_per_week_capacity",
      "prompt": "What is your weekly capacity in terms of your operating unit?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "avg_units_per_week_year1",
      "prompt": "In year 1, what is your expected average units per week?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "utilization_rate",
      "prompt": "What utilization rate do you expect in year 1?",
      "requires_confirmation": False,
      "special": "percent",
    },
    {
      "key": "operating_weeks_per_year",
      "prompt": "How many weeks per year will you operate?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "unit_price",
      "prompt": "What is your average price per unit?",
      "requires_confirmation": False,
      "special": "number",
    },
  ],
  "cogs_model_json": [
    {
      "key": "cogs_mode",
      "prompt": "How should we model your COGS?",
      "requires_confirmation": False,
      "special": "cogs_mode",
    },
    {
      "key": "cost_per_unit",
      "prompt": "What is your average cost per unit?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "cogs_percent_of_revenue",
      "prompt": "What percent of revenue is COGS?",
      "requires_confirmation": False,
      "special": "percent",
    },
    {
      "key": "annual_total",
      "prompt": "What is your total annual COGS?",
      "requires_confirmation": False,
      "special": "number",
    },
  ],
  "gna_model_json": [
    {
      "key": "monthly_rent_expense",
      "prompt": "What is your monthly rent expense?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "monthly_software_expense",
      "prompt": "What is your monthly software expense?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "monthly_insurance_expense",
      "prompt": "What is your monthly insurance expense?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "monthly_utilities_expense",
      "prompt": "What is your monthly utilities expense?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "monthly_admin_expense",
      "prompt": "What is your monthly admin expense?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "other_operating_expense",
      "prompt": "What other monthly operating expenses should we include?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "other_monthly_debt_payments",
      "prompt": "What other monthly debt payments do you have?",
      "requires_confirmation": False,
      "special": "number",
    },
  ],
  "marketing_model_json": [
    {
      "key": "monthly_marketing_budget",
      "prompt": "What is your monthly marketing budget?",
      "requires_confirmation": False,
      "special": "number",
    },
    {
      "key": "primary_channels",
      "prompt": "What are your primary marketing channels?",
      "requires_confirmation": False,
    },
  ],
  "headcount_model_json": [
    {
      "key": "roles",
      "prompt": "What roles do you need and how many of each?",
      "requires_confirmation": False,
    },
  ],
  "people_json": [
    {
      "key": "key_people",
      "prompt": "Who are the key individuals involved and what are their roles?",
      "requires_confirmation": False,
    },
    {
      "key": "key_partners",
      "prompt": "Are there any critical third parties or partners?",
      "requires_confirmation": False,
    },
  ],
  "milestones_model_json": [
    {
      "key": "milestones",
      "prompt": "List the key milestones and expected timing.",
      "requires_confirmation": False,
    },
  ],
  "target_market_json": [
    {
      "key": "segments",
      "prompt": "Describe your target market segments in plain language.",
      "requires_confirmation": False,
    },
  ],
}


def _log_event(app, *, event: str, draft_id: str, **extra: Any) -> None:
  payload: Dict[str, Any] = {"event": event, "draft_id": str(draft_id).strip()}
  for key, value in extra.items():
    if value is None:
      continue
    payload[key] = value
  app.logger.info("intake_consult_event %s", json.dumps(payload, ensure_ascii=True))


def _focus_token(model_key: str) -> str:
  key = str(model_key or "").strip()
  if key.endswith("_json"):
    return key[: -len("_json")]
  return key


def _parse_json_maybe(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return raw


def _parse_messages(raw: Any) -> List[Dict[str, Any]]:
  parsed = _parse_json_maybe(raw)
  if isinstance(parsed, list):
    return [m for m in parsed if isinstance(m, dict)]
  return []


def _json_safe(value: Any) -> Any:
  if isinstance(value, dict):
    return {str(k): _json_safe(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_json_safe(item) for item in value]
  if isinstance(value, (datetime, date)):
    return value.isoformat()
  if isinstance(value, Decimal):
    return str(value)
  return value


def _normalize_messages_json(raw: Any) -> str:
  parsed = _parse_messages(raw)
  return json.dumps(parsed, ensure_ascii=True)


def _is_acknowledgment(text: str) -> bool:
  raw = str(text or "").strip().lower()
  return raw in {"yes", "y", "yeah", "yep", "no", "n", "ok", "okay", "sure"}


def _normalize_answer_text(raw: str) -> str:
  text = str(raw or "").strip()
  if not text:
    return ""
  text = re.sub(r"^\s*no\b[\s,.-]*(just\b[\s,.-]*)?", "", text, flags=re.IGNORECASE).strip()
  text = text.strip(" \t\r\n\"'`.,!?;:")
  text = re.sub(r"\s+", " ", text).strip()
  if not text:
    return ""
  lowered = text.lower()
  if lowered in {"n/a", "na", "not applicable", "notapplicable"}:
    return "not applicable"
  return text


def _last_substantive_user_message(messages_json: List[Dict[str, Any]]) -> str:
  for msg in reversed(messages_json):
    if str(msg.get("role") or "") != "user":
      continue
    content = str(msg.get("content") or "").strip()
    if not content:
      continue
    if _is_acknowledgment(content):
      continue
    return content
  return ""


def _build_draft_state(draft: Dict[str, Any]) -> Dict[str, Any]:
  state: Dict[str, Any] = {}
  for key, value in (draft or {}).items():
    if str(key).endswith("_json"):
      state[key] = _json_safe(_parse_json_maybe(value) or {})
    else:
      state[key] = _json_safe(value)
  operating_model = state.get("operating_model_json")
  start_date = None
  if isinstance(operating_model, dict):
    start_date = operating_model.get("start_date")
  state["business_start_date"] = start_date
  return state


def _model_payload(state: Dict[str, Any], model_key: str) -> Dict[str, Any]:
  raw = state.get(model_key) if isinstance(state, dict) else None
  return raw if isinstance(raw, dict) else {}


def _field_is_filled(model_payload: Dict[str, Any], field_key: str) -> bool:
  value = model_payload.get(field_key)
  if value is None:
    return False
  if isinstance(value, str):
    return bool(value.strip())
  if isinstance(value, list):
    return len(value) > 0
  if isinstance(value, dict):
    return len(value) > 0
  return True


def _field_is_filled_for_def(
  model_key: str,
  field_def: Dict[str, Any],
  model_payload: Dict[str, Any],
) -> bool:
  field_key = str(field_def.get("key") or "").strip()
  if not field_key:
    return False
  if str(field_def.get("special") or "").strip() == "business_type":
    business_type = model_payload.get("business_type")
    naics_6 = model_payload.get("naics_6")
    return bool(str(business_type or "").strip()) and bool(str(naics_6 or "").strip())
  return _field_is_filled(model_payload, field_key)


def _field_is_applicable(model_key: str, field_key: str, model_payload: Dict[str, Any]) -> bool:
  if model_key != "cogs_model_json":
    return True
  cogs_mode = str(model_payload.get("cogs_mode") or "").strip().lower()
  if not cogs_mode:
    return True
  if field_key == "cost_per_unit":
    return cogs_mode == "unit_based"
  if field_key == "cogs_percent_of_revenue":
    return cogs_mode == "percent_of_revenue"
  if field_key == "annual_total":
    return cogs_mode == "annual_total"
  return True


def _next_field_for_model(model_key: str, model_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  plan = FIELD_PLAN.get(model_key, [])
  for field in plan:
    key = field.get("key")
    if not isinstance(key, str):
      continue
    if not _field_is_applicable(model_key, key, model_payload):
      continue
    if not _field_is_filled_for_def(model_key, field, model_payload):
      return field
  return None


def _resolve_current_model_and_field(draft_state: Dict[str, Any], draft: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
  current_model = str(draft.get("current_model_key") or "").strip()
  current_field_key = str(draft.get("current_field_key") or "").strip()
  if current_model and current_model in MODEL_ORDER:
    model_payload = _model_payload(draft_state, current_model)
    next_field = _next_field_for_model(current_model, model_payload)
    if current_field_key:
      for field in FIELD_PLAN.get(current_model, []):
        if field.get("key") == current_field_key and _field_is_applicable(current_model, current_field_key, model_payload):
          if not _field_is_filled_for_def(current_model, field, model_payload):
            return current_model, field
    if next_field is not None:
      return current_model, next_field
  for model_key in MODEL_ORDER:
    model_payload = _model_payload(draft_state, model_key)
    next_field = _next_field_for_model(model_key, model_payload)
    if next_field is not None:
      return model_key, next_field
  return MODEL_ORDER[-1], None


def _validate_operating_patch(
  patch_payload: Dict[str, Any],
  support_data: Dict[str, Any],
) -> Tuple[bool, str]:
  if not isinstance(patch_payload, dict):
    return False, "invalid_payload"
  force_patch_only = bool(support_data.get("force_patch_only"))
  force_reason = str(support_data.get("force_patch_reason") or "").strip()

  if force_patch_only and force_reason == "start_date":
    start_date = patch_payload.get("start_date")
    if not isinstance(start_date, str) or not start_date.strip():
      return False, "missing_start_date"
    if "business_type" in patch_payload or "naics_6" in patch_payload:
      return False, "unexpected_classification_fields"
    return True, ""

  if force_patch_only and force_reason == "business_type":
    business_type = patch_payload.get("business_type")
    naics_6 = patch_payload.get("naics_6")
    if not isinstance(business_type, str) or not business_type.strip():
      return False, "missing_business_type"
    if not isinstance(naics_6, str) or not str(naics_6).strip():
      return False, "missing_naics_6"

    candidates = support_data.get("business_type_candidates")
    mapping = support_data.get("business_type_to_naics_6")
    if not isinstance(candidates, list) or not candidates:
      return False, "missing_candidates"
    if not isinstance(mapping, dict) or not mapping:
      return False, "missing_mapping"

    if business_type not in candidates:
      return False, "business_type_not_in_candidates"
    expected_naics = mapping.get(business_type)
    if not expected_naics:
      return False, "missing_naics_mapping"
    if str(expected_naics) != str(naics_6):
      return False, "naics_mismatch"
    if not str(naics_6).isdigit() or len(str(naics_6)) != 6:
      return False, "naics_invalid"
    return True, ""

  if "business_type" not in patch_payload and "naics_6" not in patch_payload:
    return True, ""

  if not force_patch_only:
    return False, "patch_not_forced"

  if force_reason and force_reason != "business_type":
    return False, "unexpected_patch_reason"

  business_type = patch_payload.get("business_type")
  naics_6 = patch_payload.get("naics_6")
  if not isinstance(business_type, str) or not business_type.strip():
    return False, "missing_business_type"
  if not isinstance(naics_6, str) or not str(naics_6).strip():
    return False, "missing_naics_6"

  candidates = support_data.get("business_type_candidates")
  mapping = support_data.get("business_type_to_naics_6")
  if not isinstance(candidates, list) or not candidates:
    return False, "missing_candidates"
  if not isinstance(mapping, dict) or not mapping:
    return False, "missing_mapping"

  if business_type not in candidates:
    return False, "business_type_not_in_candidates"
  expected_naics = mapping.get(business_type)
  if not expected_naics:
    return False, "missing_naics_mapping"
  if str(expected_naics) != str(naics_6):
    return False, "naics_mismatch"
  if not str(naics_6).isdigit() or len(str(naics_6)) != 6:
    return False, "naics_invalid"
  return True, ""


def _validate_patch_for_field(
  *,
  patch_target: str,
  patch_payload: Dict[str, Any],
  model_key: str,
  field_def: Dict[str, Any],
  support_data: Dict[str, Any],
) -> Tuple[bool, str]:
  if patch_target != model_key:
    return False, "wrong_model"
  field_key = str(field_def.get("key") or "").strip()
  if not field_key:
    return False, "missing_field_key"
  if field_def.get("special") == "business_type":
    valid, reason = _validate_operating_patch(patch_payload, support_data)
    if not valid:
      return False, reason or "invalid_business_type"
    return True, ""
  if field_key not in patch_payload:
    return False, "missing_field"
  value = patch_payload.get(field_key)
  special = str(field_def.get("special") or "").strip()
  if special == "date":
    if not isinstance(value, str) or not value.strip():
      return False, "invalid_date"
  if special == "number":
    try:
      float(value)
    except Exception:
      return False, "invalid_number"
  if special == "percent":
    raw = str(value or "").strip().replace("%", "")
    try:
      float(raw)
    except Exception:
      return False, "invalid_percent"
  if special == "sales_modality":
    raw = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    mapping = {
      "physical": "physical",
      "in person": "physical",
      "inperson": "physical",
      "on site": "physical",
      "onsite": "physical",
      "online": "online",
      "digital": "online",
      "virtual": "online",
      "hybrid": "hybrid",
    }
    normalized = mapping.get(raw)
    if not normalized:
      return False, "invalid_sales_modality"
    patch_payload[field_key] = normalized
  if special == "geographic_scope":
    raw = str(value or "").strip().lower()
    mapping = {
      "local": "local",
      "regional": "regional",
      "region": "regional",
      "national": "national",
      "nationwide": "national",
      "international": "international",
      "global": "international",
      "worldwide": "international",
    }
    normalized = mapping.get(raw)
    if not normalized:
      return False, "invalid_geographic_scope"
    patch_payload[field_key] = normalized
  if special == "capacity_driver":
    raw = str(value or "").strip().lower()
    mapping = {
      "labor": "labor",
      "people": "labor",
      "staff": "labor",
      "staffing": "labor",
      "system": "system",
      "systems": "system",
      "process": "system",
      "demand": "demand",
      "sales": "demand",
      "customers": "demand",
    }
    normalized = mapping.get(raw)
    if not normalized:
      return False, "invalid_capacity_driver"
    patch_payload[field_key] = normalized
  if special == "legal_entity":
    if not isinstance(value, str) or not value.strip():
      return False, "invalid_legal_entity"
  if special == "cogs_mode":
    raw = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    mapping = {
      "unit based": "unit_based",
      "per unit": "unit_based",
      "unit": "unit_based",
      "percent of revenue": "percent_of_revenue",
      "percentage of revenue": "percent_of_revenue",
      "percent": "percent_of_revenue",
      "percentage": "percent_of_revenue",
      "annual total": "annual_total",
      "annual": "annual_total",
      "total": "annual_total",
    }
    normalized = mapping.get(raw)
    if not normalized:
      return False, "invalid_cogs_mode"
    patch_payload[field_key] = normalized
  return True, ""


def _fallback_value_for_field(field_def: Dict[str, Any], user_message: str) -> Optional[Any]:
  raw = _normalize_answer_text(user_message)
  if not raw:
    return None
  if _is_acknowledgment(raw):
    return None
  special = str(field_def.get("special") or "").strip()
  if special == "business_type":
    return None
  if special == "date":
    return raw
  if special == "number":
    cleaned = raw.replace(",", "").replace("$", "").strip()
    try:
      value = float(cleaned)
    except Exception:
      return None
    if value.is_integer():
      return int(value)
    return value
  if special == "percent":
    cleaned = raw.replace("%", "").replace(",", "").strip()
    try:
      value = float(cleaned)
    except Exception:
      return None
    return value
  if special == "sales_modality":
    lowered = raw.lower().replace("-", " ").replace("_", " ")
    mapping = {
      "physical": "physical",
      "in person": "physical",
      "inperson": "physical",
      "on site": "physical",
      "onsite": "physical",
      "online": "online",
      "digital": "online",
      "virtual": "online",
      "hybrid": "hybrid",
    }
    return mapping.get(lowered)
  if special == "geographic_scope":
    lowered = raw.lower()
    mapping = {
      "local": "local",
      "regional": "regional",
      "region": "regional",
      "national": "national",
      "nationwide": "national",
      "international": "international",
      "global": "international",
      "worldwide": "international",
    }
    return mapping.get(lowered)
  if special == "capacity_driver":
    lowered = raw.lower()
    mapping = {
      "labor": "labor",
      "people": "labor",
      "staff": "labor",
      "staffing": "labor",
      "system": "system",
      "systems": "system",
      "process": "system",
      "demand": "demand",
      "sales": "demand",
      "customers": "demand",
    }
    return mapping.get(lowered)
  if special == "cogs_mode":
    lowered = raw.lower().replace("-", " ").replace("_", " ")
    mapping = {
      "unit based": "unit_based",
      "per unit": "unit_based",
      "unit": "unit_based",
      "percent of revenue": "percent_of_revenue",
      "percentage of revenue": "percent_of_revenue",
      "percent": "percent_of_revenue",
      "percentage": "percent_of_revenue",
      "annual total": "annual_total",
      "annual": "annual_total",
      "total": "annual_total",
    }
    return mapping.get(lowered)
  return raw


def _fallback_business_type_patch(support_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
  candidates = support_data.get("business_type_candidates")
  mapping = support_data.get("business_type_to_naics_6")
  hinted_business_type = str(support_data.get("business_type_hint") or "").strip()
  hinted_naics = str(support_data.get("naics_6_hint") or "").strip()
  if not isinstance(candidates, list) or not candidates:
    return None
  if not isinstance(mapping, dict) or not mapping:
    return None
  if hinted_business_type:
    naics_value = hinted_naics or mapping.get(hinted_business_type)
    if naics_value:
      return {"business_type": hinted_business_type, "naics_6": str(naics_value)}
  for bt in candidates:
    if bt in mapping:
      naics = mapping.get(bt)
      if naics:
        return {"business_type": str(bt), "naics_6": str(naics)}
  return None


def _select_business_type_hint(
  candidates: Any,
  mapping: Any,
  user_text: str,
) -> Optional[Tuple[str, str]]:
  if not isinstance(candidates, list) or not candidates:
    return None
  if not isinstance(mapping, dict) or not mapping:
    return None
  base = " ".join(str(user_text or "").lower().split())
  if not base:
    return None
  try:
    from difflib import SequenceMatcher
  except Exception:
    SequenceMatcher = None  # type: ignore

  tokens = {t for t in base.replace("/", " ").replace("-", " ").split() if len(t) >= 3}
  best_bt = None
  best_score = (-1, -1.0, 0)
  for bt in candidates:
    if bt not in mapping:
      continue
    btl = str(bt or "").lower()
    token_score = sum(1 for t in tokens if t in btl) if tokens else 0
    ratio = SequenceMatcher(None, base, btl).ratio() if SequenceMatcher else 0.0
    score = (token_score, ratio, -len(btl))
    if score > best_score:
      best_score = score
      best_bt = bt
  if not best_bt:
    return None
  naics = mapping.get(best_bt)
  if not naics:
    return None
  return str(best_bt), str(naics)


def _is_affirmative(text: str) -> bool:
  raw = str(text or "").strip().lower()
  if not raw:
    return False
  tokens = {"yes", "yep", "yeah", "correct", "right", "true", "affirmative", "ok", "okay", "sure"}
  if raw in tokens:
    return True
  if raw.startswith("yes"):
    return True
  if raw.startswith("yeah") or raw.startswith("yep"):
    return True
  return any(
    tok in raw
    for tok in (
      "that's right",
      "that is right",
      "sounds right",
      "that's correct",
      "that is correct",
    )
  )


def _is_date_like(text: str) -> bool:
  raw = str(text or "").strip().lower()
  if not raw:
    return False
  if any(ch.isdigit() for ch in raw) and "-" in raw:
    return True
  months = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
  )
  return any(month in raw for month in months)


def _next_missing_operating_field(state: Dict[str, Any]) -> Optional[str]:
  operating_model = state.get("operating_model_json") if isinstance(state, dict) else None
  if not isinstance(operating_model, dict):
    return "start_date"
  if not str(operating_model.get("start_date") or "").strip():
    return "start_date"
  if not str(operating_model.get("business_type") or "").strip():
    return "business_type"
  if not str(operating_model.get("naics_6") or "").strip():
    return "naics_6"
  return None


def _looks_like_confirmation(text: str) -> bool:
  raw = str(text or "").lower()
  if "?" not in raw:
    return False
  segment = raw.rsplit("?", 1)[0]
  segment = segment.split(".")[-1]
  segment = segment.split("\n")[-1].strip()
  phrases = (
    "does that sound right",
    "does that sound correct",
    "is that correct",
    "is that right",
    "is that accurate",
    "is that an accurate",
    "is that a good summary",
    "is this accurate",
    "does that capture",
    "does this capture",
    "does that mean",
    "does that describe",
    "does that fit",
    "does that sum",
    "does that fully describe",
    "does that reflect",
    "does this reflect",
    "does that align",
    "does this align",
    "am i understanding",
    "am i hearing",
    "just to be sure",
    "just to be safe",
    "is that ok",
    "is that okay",
    "is this ok",
    "is this okay",
    "does that work",
    "does this work",
    "would that work",
    "would this work",
    "sound right",
    "sound correct",
    "is this the",
    "is that the",
    "is this correct",
    "does that match",
    "does the description",
    "fully capture",
    "did i understand",
    "just to confirm",
    "to confirm",
    "confirm that",
    "confirm this",
    "confirm it",
  )
  if any(phrase in segment for phrase in phrases):
    return True
  return segment.endswith(("right", "correct", "ok", "okay"))


def _violates_single_question(text: str) -> bool:
  raw = str(text or "")
  if "?" not in raw:
    return False
  if raw.count("?") > 1:
    return True
  segment = raw.rsplit("?", 1)[0]
  segment = segment.split(".")[-1]
  segment = segment.split("\n")[-1]
  lowered = segment.lower()
  if (
    "for example" in lowered
    or "for instance" in lowered
    or "such as" in lowered
    or "e.g." in lowered
    or " like " in lowered
  ):
    return True
  if " or " in lowered or " either " in lowered or " whether " in lowered or " which of " in lowered:
    return True
  return False


def _sanitize_single_question(text: str) -> str:
  raw = str(text or "").strip()
  if not raw:
    return raw
  if "?" in raw:
    raw = raw[: raw.find("?") + 1].strip()
  lowered = raw.lower()
  for marker in (" or ", " either ", " whether ", " which of "):
    idx = lowered.find(marker)
    if idx != -1:
      raw = raw[:idx].strip().rstrip(",")
      break
  lowered = raw.lower()
  for marker in ("for example", "for instance", "such as", "e.g.", " like "):
    idx = lowered.find(marker)
    if idx != -1:
      raw = raw[:idx].strip().rstrip(",")
      break
  return raw


def _violates_classification_exposure(text: str, support_data: Optional[Dict[str, Any]] = None) -> bool:
  lowered = str(text or "").lower()
  if not lowered:
    return False
  markers = (
    "naics",
    "industry code",
    "classification",
    "classify",
    "business type",
    "category",
    "classification code",
  )
  return any(marker in lowered for marker in markers)


def _sanitize_classification_exposure(text: str, support_data: Optional[Dict[str, Any]] = None) -> str:
  raw = str(text or "").strip()
  if not raw:
    return raw
  parts = [p.strip() for p in raw.replace("\n", " ").split(".") if p.strip()]
  kept = []
  for part in parts:
    if _violates_classification_exposure(part, support_data):
      continue
    kept.append(part)
  if not kept:
    return raw
  return ". ".join(kept).strip()


def _violates_recent_answer(text: str, pending_key: str, user_message: str) -> bool:
  if not str(user_message or "").strip():
    return False
  if not pending_key:
    return False
  lowered = str(text or "").lower()
  if "?" not in lowered:
    return False
  field_def = None
  for fields in FIELD_PLAN.values():
    for field in fields:
      if field.get("key") == pending_key:
        field_def = field
        break
    if field_def:
      break
  if not field_def:
    return False
  prompt = str(field_def.get("prompt") or "").strip().lower()
  if prompt and prompt in lowered:
    return True
  tokens = [tok.strip(".,!?;:\"'()[]{}") for tok in prompt.split()]
  tokens = [tok for tok in tokens if len(tok) >= 4]
  if not tokens:
    return False
  hits = sum(1 for tok in tokens if tok in lowered)
  threshold = 2 if len(tokens) >= 2 else 1
  return hits >= threshold


def _violates_no_confirmation(text: str, support_data: Dict[str, Any]) -> bool:
  if not support_data.get("no_confirmation"):
    return False
  return _looks_like_confirmation(text)


def _question_mentions_current_field(text: str, support_data: Dict[str, Any]) -> bool:
  if "?" not in str(text or ""):
    return False
  if support_data.get("require_confirmation"):
    return True
  if support_data.get("force_business_summary"):
    return True
  field_key = str(support_data.get("current_field_key") or "").strip()
  field_prompt = str(support_data.get("current_field_prompt") or "").strip()
  if field_key == "business_type":
    return True
  if not field_key or not field_prompt:
    return True
  lowered = str(text or "").lower()
  label_tokens = [tok for tok in field_key.replace("_", " ").split() if len(tok) >= 4]
  prompt_tokens = [tok for tok in field_prompt.lower().split() if len(tok) >= 4]
  stopwords = {
    "business",
    "company",
    "your",
    "primary",
    "main",
    "monthly",
    "expense",
    "planned",
    "expected",
    "typical",
    "per",
    "year",
    "years",
    "week",
    "weeks",
    "unit",
    "units",
    "operating",
    "number",
    "total",
  }
  tokens = {
    tok.strip(".,!?;:\"'()[]{}")
    for tok in (label_tokens + prompt_tokens)
    if tok and tok.strip(".,!?;:\"'()[]{}") not in stopwords
  }
  if not tokens:
    return True
  return any(tok in lowered for tok in tokens)


def _violates_missing_summary(text: str, user_message: str, support_data: Dict[str, Any]) -> bool:
  if not support_data.get("require_confirmation"):
    return False
  if not support_data.get("force_business_summary"):
    return False
  if not str(user_message or "").strip():
    return False
  lowered = str(text or "").lower()
  if not lowered:
    return True
  if str(support_data.get("current_field_key") or "") == "business_type":
    if "describe what your business does" in lowered or "what your business does day to day" in lowered:
      return True
  raw_tokens = [tok.strip(".,!?;:\"'()[]{}") for tok in str(user_message or "").lower().split()]
  min_len = 3 if str(support_data.get("current_field_key") or "") == "business_type" else 4
  tokens = [tok for tok in raw_tokens if len(tok) >= min_len]
  if not tokens:
    return False
  return not any(tok in lowered for tok in tokens)


def _violates_answered_fields(text: str, draft_state: Dict[str, Any]) -> bool:
  lowered = str(text or "").lower()
  if "?" not in lowered:
    return False
  if not isinstance(draft_state, dict):
    return False
  for model_key, fields in FIELD_PLAN.items():
    model_payload = draft_state.get(model_key)
    if not isinstance(model_payload, dict):
      continue
    for field in fields:
      field_key = str(field.get("key") or "").strip()
      if not field_key:
        continue
      if not _field_is_filled_for_def(model_key, field, model_payload):
        continue
      label = field_key.replace("_", " ").strip()
      if label and label in lowered:
        return True
  return False


def _requires_question(draft_state: Dict[str, Any]) -> bool:
  _, field_def = _resolve_current_model_and_field(draft_state, {"current_model_key": ""})
  return field_def is not None


def _is_valid_patch_message(message: str) -> bool:
  text = str(message or "").strip()
  if not text:
    return False
  decoder = json.JSONDecoder()
  for idx, ch in enumerate(text):
    if ch != "{":
      continue
    try:
      parsed, _ = decoder.raw_decode(text[idx:])
    except Exception:
      continue
    if not isinstance(parsed, dict) or len(parsed) != 1:
      continue
    key = next(iter(parsed.keys()))
    value = parsed.get(key)
    return key in MODEL_COLUMNS and isinstance(value, dict)
  return False



def _call_llm(
  *,
  messages_json: List[Dict[str, Any]],
  draft_state: Dict[str, Any],
  user_message: str,
  support_data: Optional[Dict[str, Any]] = None,
) -> str:
  try:
    from openai import OpenAI  # type: ignore
  except Exception as exc:  # pragma: no cover
    raise RuntimeError("OpenAI client is not available in this environment.") from exc

  api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")

  model = (
    (os.getenv("INTAKE_CONSULT_MODEL") or "").strip()
    or (os.getenv("OPENAI_MODEL") or "").strip()
    or "gpt-4.1-mini"
  )
  client = OpenAI(api_key=api_key)

  payload = {
    "messages_json": messages_json,
    "draft_state": draft_state,
    "user_message": user_message,
    "support_data": support_data or {},
  }
  flag_lines = []
  try:
    if isinstance(support_data, dict):
      for key in ("current_field_key", "current_field_prompt"):
        value = str(support_data.get(key) or "").strip()
        if value:
          flag_lines.append(f"{key}={value}")
      for key in ("force_business_summary", "require_confirmation", "require_question"):
        if support_data.get(key):
          flag_lines.append(f"{key}=true")
      hint = str(support_data.get("business_description_hint") or "").strip()
      if hint:
        flag_lines.append(f"business_description_hint={hint}")
      hint_bt = str(support_data.get("business_type_hint") or "").strip()
      hint_naics = str(support_data.get("naics_6_hint") or "").strip()
      if hint_bt and hint_naics:
        flag_lines.append(f"business_type_hint={hint_bt}")
        flag_lines.append(f"naics_6_hint={hint_naics}")
    biz_name = str((draft_state or {}).get("business_name") or "").strip()
    if biz_name:
      flag_lines.append(f"business_name={biz_name}")
  except Exception:
    flag_lines = []

  user_content = json.dumps(payload, ensure_ascii=True)
  if flag_lines:
    user_content = "IMPORTANT FLAGS:\n" + "\n".join(flag_lines) + "\n\n" + user_content

  response = client.chat.completions.create(
    model=model,
    messages=[
      {"role": "system", "content": SYSTEM_PROMPT},
      {"role": "user", "content": user_content},
    ],
  )
  content = response.choices[0].message.content if response.choices else ""
  return str(content or "")


def post_intake_consult_session_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  try:
    conn = get_mysql_connection()
  except Exception as exc:
    app.logger.exception("Failed to connect to MySQL: %s", exc)
    return jsonify({"error": "server_error"}), 500

  try:
    draft = create_draft(conn)
    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft.get("draft_id") or "").strip(),
        "client_id": str(draft.get("client_id") or "").strip(),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_intake_consult_draft_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = request.args.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400

  try:
    conn = get_mysql_connection()
  except Exception as exc:
    app.logger.exception("Failed to connect to MySQL: %s", exc)
    return jsonify({"error": "server_error"}), 500

  try:
    draft = get_draft(conn, draft_id=str(draft_id).strip())
    if not draft:
      return jsonify({"error": "not_found", "detail": "draft_id was not found"}), 404

    messages_json = _normalize_messages_json(draft.get("messages_json"))
    draft_status = draft.get("draft_status") or draft.get("status") or ""
    operating_model = _parse_json_maybe(draft.get("operating_model_json"))
    start_date = None
    if isinstance(operating_model, dict):
      start_date = operating_model.get("start_date")

    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "draft_status": str(draft_status),
        "active_focus": str(draft.get("active_focus") or ""),
        "interaction_mode": str(draft.get("interaction_mode") or "chat"),
        "ops_confirmed": bool(draft.get("ops_confirmed")),
        "market_confirmed": bool(draft.get("market_confirmed")),
        "people_confirmed": bool(draft.get("people_confirmed")),
        "financials_confirmed": bool(draft.get("financials_confirmed")),
        "consistency_passed": bool(draft.get("consistency_passed")),
        "business_name": draft.get("business_name"),
        "business_address": draft.get("business_address") or draft.get("address"),
        "business_start_date": start_date,
        "address_street": draft.get("address_street"),
        "address_city": draft.get("address_city"),
        "address_state": draft.get("address_state"),
        "address_zip": draft.get("address_zip"),
        "address_country": draft.get("address_country"),
        "messages_json": messages_json,
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def post_intake_consult_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = str(payload.get("draft_id") or "").strip()
  if not draft_id:
    return jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400

  try:
    conn = get_mysql_connection()
  except Exception as exc:
    app.logger.exception("Failed to connect to MySQL: %s", exc)
    return jsonify({"error": "server_error"}), 500

  try:
    draft = get_draft(conn, draft_id=draft_id)
    if not draft:
      return jsonify({"error": "not_found", "detail": "draft_id was not found"}), 404

    business_updates: Dict[str, Any] = {}
    if "business_name" in payload:
      business_updates["business_name"] = str(payload.get("business_name") or "").strip() or None
    if "address" in payload:
      business_updates["business_address"] = str(payload.get("address") or "").strip() or None
    for key in ("address_street", "address_city", "address_state", "address_zip", "address_country"):
      if key in payload:
        business_updates[key] = str(payload.get(key) or "").strip() or None

    if business_updates:
      update_draft(conn, draft_id=draft_id, updates=business_updates)
      draft.update(business_updates)

    user_message = str(payload.get("message") or "")
    messages_json = _parse_messages(draft.get("messages_json"))
    draft_state = _build_draft_state(draft)
    pending_question_key = str(draft.get("pending_question_key") or "").strip()
    pending_question_kind = str(draft.get("pending_question_kind") or "").strip()

    support_data: Dict[str, Any] = {}
    try:
      from pull_intake_support_data.naics_context import build_naics_context  # type: ignore

      candidate_messages = list(messages_json)
      if user_message.strip():
        candidate_messages.append({"role": "user", "content": user_message})
      support_data = build_naics_context(conn=conn, messages=candidate_messages)
    except Exception:
      support_data = {}

    current_model_key, current_field_def = _resolve_current_model_and_field(draft_state, draft)
    current_field_key = str(current_field_def.get("key") or "").strip() if current_field_def else ""
    current_field_prompt = str(current_field_def.get("prompt") or "").strip() if current_field_def else ""
    requires_confirmation = bool(current_field_def.get("requires_confirmation")) if current_field_def else False

    if pending_question_key and pending_question_key != current_field_key:
      pending_question_key = ""
      pending_question_kind = ""

    current_updates: Dict[str, Any] = {}
    if current_model_key and str(draft.get("current_model_key") or "") != current_model_key:
      current_updates["current_model_key"] = current_model_key
    if current_field_key and str(draft.get("current_field_key") or "") != current_field_key:
      current_updates["current_field_key"] = current_field_key
    if current_updates:
      update_draft(conn, draft_id=draft_id, updates=current_updates)
      draft.update(current_updates)

    support_data = dict(support_data)
    support_data["current_model_key"] = current_model_key
    support_data["current_field_key"] = current_field_key
    support_data["current_field_prompt"] = current_field_prompt
    support_data["current_field_requires_confirmation"] = requires_confirmation
    if current_field_def:
      support_data["no_confirmation"] = not requires_confirmation
      if str(current_field_def.get("special") or "").strip() == "business_type":
        hint_text = _normalize_answer_text(user_message) or _last_substantive_user_message(messages_json)
        if hint_text:
          hint = _select_business_type_hint(
            support_data.get("business_type_candidates"),
            support_data.get("business_type_to_naics_6"),
            hint_text,
          )
        else:
          hint = None
        if hint:
          support_data["business_type_hint"] = hint[0]
          support_data["naics_6_hint"] = hint[1]
        last_business_description = hint_text
        if last_business_description:
          support_data["business_description_hint"] = last_business_description

    parsed_answer_value: Optional[Any] = None
    if (
      user_message.strip()
      and current_field_def
      and str(current_field_def.get("special") or "").strip() != "business_type"
    ):
      parsed_answer_value = _fallback_value_for_field(current_field_def, user_message)

    force_patch_only = False
    force_patch_reason = ""
    conversation_only = False
    require_question = False
    require_confirmation = False

    if current_field_key and (requires_confirmation or (pending_question_kind == "confirm" and pending_question_key == current_field_key)) and _is_affirmative(user_message):
      force_patch_only = True
      force_patch_reason = current_field_key
    elif not current_field_key:
      conversation_only = True
      support_data["intake_complete"] = True
    elif pending_question_kind == "confirm" and pending_question_key == current_field_key:
      if _is_affirmative(user_message):
        force_patch_only = True
        force_patch_reason = current_field_key
      else:
        conversation_only = True
        require_question = True
    elif pending_question_kind == "ask" and pending_question_key == current_field_key:
      if requires_confirmation:
        conversation_only = True
        require_question = True
        require_confirmation = True
        if current_field_def.get("special") == "business_type":
          support_data["force_business_summary"] = True
      else:
        if parsed_answer_value is None:
          conversation_only = True
          require_question = True
        else:
          force_patch_only = True
          force_patch_reason = current_field_key
    else:
      conversation_only = True
      require_question = True
    if (
      current_field_def
      and str(current_field_def.get("special") or "").strip() == "business_type"
      and user_message.strip()
      and not _is_acknowledgment(user_message)
      and not _is_affirmative(user_message)
      and not force_patch_only
    ):
      conversation_only = True
      require_question = True
      require_confirmation = True
      support_data["force_business_summary"] = True

    if force_patch_only:
      support_data["force_patch_only"] = True
      support_data["force_patch_target"] = current_model_key
      support_data["force_patch_reason"] = force_patch_reason
      support_data["force_patch_field_key"] = current_field_key
    if conversation_only:
      support_data["conversation_only"] = True
    if require_question:
      support_data["require_question"] = True
    if require_confirmation:
      support_data["require_confirmation"] = True
    support_data["no_classification_exposure"] = bool(conversation_only)
    chat_support_data = dict(support_data)

    assistant_content = ""
    patch_target: Optional[str] = None
    patch_payload: Optional[Dict[str, Any]] = None
    patch_key_logged: Optional[str] = None
    auto_persisted = False

    if (
      user_message.strip()
      and current_field_def
      and str(current_field_def.get("special") or "").strip() != "business_type"
    ):
      candidate_value = parsed_answer_value
      if candidate_value is not None:
        candidate_payload = {current_field_key: candidate_value}
        valid, _ = _validate_patch_for_field(
          patch_target=current_model_key,
          patch_payload=candidate_payload,
          model_key=current_model_key,
          field_def=current_field_def,
          support_data=support_data,
        )
        if valid:
          patch_target = current_model_key
          patch_payload = candidate_payload
          auto_persisted = True
    if (
      not auto_persisted
      and current_field_def
      and str(current_field_def.get("special") or "").strip() == "business_type"
      and force_patch_only
      and force_patch_reason == "business_type"
    ):
      candidate_payload = _fallback_business_type_patch(support_data)
      if candidate_payload is not None:
        patch_target = current_model_key
        patch_payload = candidate_payload
        auto_persisted = True

    if not auto_persisted:
      _log_event(app, event="llm_call_start", draft_id=draft_id, phase="initial")
      llm_started = time.time()
      try:
        assistant_content = _call_llm(
          messages_json=messages_json,
          draft_state=draft_state,
          user_message=user_message,
          support_data=support_data,
        )
      finally:
        duration_ms = int((time.time() - llm_started) * 1000)
        _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="initial")
      chat_support_data = dict(support_data)

    def _parse_patch(content: str) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
      text = str(content or "").strip()
      if not text:
        return None, None, None
      decoder = json.JSONDecoder()
      for idx, ch in enumerate(text):
        if ch != "{":
          continue
        try:
          parsed_local, _ = decoder.raw_decode(text[idx:])
        except Exception:
          continue
        if not isinstance(parsed_local, dict) or len(parsed_local) != 1:
          continue
        key = next(iter(parsed_local.keys()))
        value = parsed_local.get(key)
        if key in MODEL_COLUMNS and isinstance(value, dict):
          return key, value, key
        return None, None, key if key in MODEL_COLUMNS else None
      return None, None, None

    if not auto_persisted:
      patch_target, patch_payload, patch_key_logged = _parse_patch(assistant_content)
    if patch_key_logged is not None:
      _log_event(app, event="patch_received", draft_id=draft_id, target_key=patch_key_logged or "")

    patch_valid = True
    patch_invalid_reason = ""
    if patch_target and isinstance(patch_payload, dict) and current_field_def:
      patch_valid, patch_invalid_reason = _validate_patch_for_field(
        patch_target=patch_target,
        patch_payload=patch_payload,
        model_key=current_model_key,
        field_def=current_field_def,
        support_data=support_data,
      )

    if patch_target and isinstance(patch_payload, dict) and not patch_valid:
      _log_event(
        app,
        event="patch_rejected",
        draft_id=draft_id,
        target_key=patch_target,
        reason=patch_invalid_reason,
      )
      support_data_retry = dict(support_data)
      support_data_retry["validation_error"] = patch_invalid_reason
      support_data_retry["invalid_patch"] = {patch_target: patch_payload}
      _log_event(app, event="llm_call_start", draft_id=draft_id, phase="validation_retry")
      llm_started = time.time()
      try:
        assistant_content = _call_llm(
          messages_json=messages_json,
          draft_state=draft_state,
          user_message=user_message,
          support_data=support_data_retry,
        )
      finally:
        duration_ms = int((time.time() - llm_started) * 1000)
        _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="validation_retry")

      patch_target, patch_payload, patch_key_logged = _parse_patch(assistant_content)
      if patch_key_logged is not None:
        _log_event(app, event="patch_received", draft_id=draft_id, target_key=patch_key_logged or "")
      patch_valid = True
      patch_invalid_reason = ""
      if patch_target and isinstance(patch_payload, dict) and current_field_def:
        patch_valid, patch_invalid_reason = _validate_patch_for_field(
          patch_target=patch_target,
          patch_payload=patch_payload,
          model_key=current_model_key,
          field_def=current_field_def,
          support_data=support_data,
        )
    if patch_target and isinstance(patch_payload, dict) and not patch_valid:
        _log_event(
          app,
          event="patch_rejected",
          draft_id=draft_id,
          target_key=patch_target,
          reason=patch_invalid_reason,
        )
        patch_target = None
        patch_payload = None

    if force_patch_only and not patch_target:
      attempts = 0
      last_invalid_reason = patch_invalid_reason
      while attempts < MAX_FORCE_PATCH_ATTEMPTS and not patch_target:
        _log_event(app, event="patch_forced_retry", draft_id=draft_id, target_key=current_model_key)
        support_data_retry = dict(support_data)
        support_data_retry["force_patch_only"] = True
        support_data_retry["force_patch_target"] = current_model_key
        support_data_retry["force_patch_reason"] = force_patch_reason
        support_data_retry["force_patch_field_key"] = current_field_key
        if last_invalid_reason:
          support_data_retry["validation_error"] = last_invalid_reason
        _log_event(app, event="llm_call_start", draft_id=draft_id, phase="force_patch_retry")
        llm_started = time.time()
        try:
          assistant_content = _call_llm(
            messages_json=messages_json,
            draft_state=draft_state,
            user_message=user_message,
            support_data=support_data_retry,
          )
        finally:
          duration_ms = int((time.time() - llm_started) * 1000)
          _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="force_patch_retry")

        patch_target, patch_payload, patch_key_logged = _parse_patch(assistant_content)
        if patch_key_logged is not None:
          _log_event(app, event="patch_received", draft_id=draft_id, target_key=patch_key_logged or "")
        patch_valid = True
        patch_invalid_reason = ""
        if patch_target and isinstance(patch_payload, dict) and current_field_def:
          patch_valid, patch_invalid_reason = _validate_patch_for_field(
            patch_target=patch_target,
            patch_payload=patch_payload,
            model_key=current_model_key,
            field_def=current_field_def,
            support_data=support_data,
          )
        if patch_target and isinstance(patch_payload, dict) and not patch_valid:
          _log_event(
            app,
            event="patch_rejected",
            draft_id=draft_id,
            target_key=patch_target,
            reason=patch_invalid_reason,
          )
          patch_target = None
          patch_payload = None
          last_invalid_reason = patch_invalid_reason
        attempts += 1

    if force_patch_only and not patch_target and force_patch_reason == "business_type":
      fallback_patch = _fallback_business_type_patch(support_data)
      if fallback_patch and current_field_def:
        patch_target = current_model_key
        patch_payload = fallback_patch
        patch_valid, patch_invalid_reason = _validate_patch_for_field(
          patch_target=patch_target,
          patch_payload=patch_payload,
          model_key=current_model_key,
          field_def=current_field_def,
          support_data=support_data,
        )
        if not patch_valid:
          patch_target = None
          patch_payload = None

    if patch_target and isinstance(patch_payload, dict):
      focus_value = _focus_token(patch_target)
      merged_payload = patch_payload
      if patch_target.endswith("_json"):
        existing_raw = draft.get(patch_target)
        existing_payload = _parse_json_maybe(existing_raw)
        if isinstance(existing_payload, dict):
          merged_payload = dict(existing_payload)
          merged_payload.update(patch_payload)
      updated_state = dict(draft_state)
      updated_state[patch_target] = merged_payload
      next_model_key, next_field_def = _resolve_current_model_and_field(updated_state, {"current_model_key": ""})
      pending_updates: Dict[str, Any] = {"pending_question_key": None, "pending_question_kind": None}
      if next_model_key:
        pending_updates["current_model_key"] = next_model_key
      if next_field_def:
        pending_updates["current_field_key"] = str(next_field_def.get("key") or "")
      else:
        pending_updates["current_field_key"] = ""
      update_draft(
        conn,
        draft_id=draft_id,
        updates={patch_target: merged_payload, "active_focus": focus_value, **pending_updates},
      )
      _log_event(app, event="patch_persisted", draft_id=draft_id, target_key=patch_target)
    elif patch_key_logged is not None:
      _log_event(app, event="patch_ignored", draft_id=draft_id, target_key=patch_key_logged or "")

    assistant_content_for_chat = assistant_content
    if not patch_target and _is_valid_patch_message(assistant_content_for_chat):
      attempts = 0
      while _is_valid_patch_message(assistant_content_for_chat) and attempts < MAX_CONVERSATION_ATTEMPTS:
        needs_question = _requires_question(draft_state) and "?" not in assistant_content_for_chat
        _log_event(app, event="conversation_retry", draft_id=draft_id)
        llm_started = time.time()
        try:
          retry_support_data = dict(support_data)
          for key in (
            "force_patch_only",
            "force_patch_target",
            "force_patch_reason",
            "validation_error",
            "invalid_patch",
          ):
            retry_support_data.pop(key, None)
          retry_support_data["conversation_only"] = True
          retry_support_data["no_classification_exposure"] = True
          if needs_question:
            retry_support_data["require_question"] = True
          retry_message = user_message
          if patch_target and needs_question:
            retry_message = "continue"
          assistant_content_for_chat = _call_llm(
            messages_json=messages_json,
            draft_state=draft_state,
            user_message=retry_message,
            support_data=retry_support_data,
          )
          chat_support_data = dict(retry_support_data)
        finally:
          duration_ms = int((time.time() - llm_started) * 1000)
          _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="conversation_retry")
        attempts += 1
    if patch_target:
      draft = get_draft(conn, draft_id=draft_id)
      if draft:
        draft_state = _build_draft_state(draft)
      support_data_continuation = dict(support_data)
      for key in (
        "force_patch_only",
        "force_patch_target",
        "force_patch_reason",
        "validation_error",
        "invalid_patch",
      ):
        support_data_continuation.pop(key, None)
      next_model_key, next_field_def = _resolve_current_model_and_field(draft_state, draft or {})
      next_field_key = str(next_field_def.get("key") or "").strip() if next_field_def else ""
      next_field_prompt = str(next_field_def.get("prompt") or "").strip() if next_field_def else ""
      next_requires_confirmation = bool(next_field_def.get("requires_confirmation")) if next_field_def else False
      support_data_continuation["current_model_key"] = next_model_key
      support_data_continuation["current_field_key"] = next_field_key
      support_data_continuation["current_field_prompt"] = next_field_prompt
      support_data_continuation["current_field_requires_confirmation"] = next_requires_confirmation
      if next_field_def:
        support_data_continuation["no_confirmation"] = not next_requires_confirmation
      support_data_continuation["conversation_only"] = True
      support_data_continuation["no_classification_exposure"] = True
      if next_field_key:
        support_data_continuation["require_question"] = True
      else:
        support_data_continuation["intake_complete"] = True
      _log_event(app, event="llm_call_start", draft_id=draft_id, phase="continuation")
      llm_started = time.time()
      try:
        assistant_content_for_chat = _call_llm(
          messages_json=messages_json,
          draft_state=draft_state,
          user_message="",
          support_data=support_data_continuation,
        )
        chat_support_data = dict(support_data_continuation)
      finally:
        duration_ms = int((time.time() - llm_started) * 1000)
        _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="continuation")

      if _is_valid_patch_message(assistant_content_for_chat):
        attempts = 0
        while _is_valid_patch_message(assistant_content_for_chat) and attempts < MAX_CONVERSATION_ATTEMPTS:
          _log_event(app, event="continuation_retry", draft_id=draft_id)
          llm_started = time.time()
          try:
            assistant_content_for_chat = _call_llm(
              messages_json=messages_json,
              draft_state=draft_state,
              user_message="continue",
              support_data=support_data_continuation,
            )
            chat_support_data = dict(support_data_continuation)
          finally:
            duration_ms = int((time.time() - llm_started) * 1000)
            _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="continuation_retry")
          attempts += 1
    if not assistant_content_for_chat.strip():
      _log_event(app, event="conversation_retry", draft_id=draft_id)
      llm_started = time.time()
      try:
        retry_support_data = dict(support_data)
        for key in (
          "force_patch_only",
          "force_patch_target",
          "force_patch_reason",
          "validation_error",
          "invalid_patch",
        ):
          retry_support_data.pop(key, None)
        retry_support_data["conversation_only"] = True
        retry_support_data["no_classification_exposure"] = True
        if _requires_question(draft_state):
          retry_support_data["require_question"] = True
        assistant_content_for_chat = _call_llm(
          messages_json=messages_json,
          draft_state=draft_state,
          user_message="continue",
          support_data=retry_support_data,
        )
        chat_support_data = dict(retry_support_data)
      finally:
        duration_ms = int((time.time() - llm_started) * 1000)
        _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="conversation_retry")

    if assistant_content_for_chat.strip() and not _is_valid_patch_message(assistant_content_for_chat):
      attempts = 0
      while attempts < MAX_CONVERSATION_ATTEMPTS:
        needs_question = bool(chat_support_data.get("require_question") or _requires_question(draft_state))
        needs_question = needs_question and "?" not in assistant_content_for_chat
        if not (
          _violates_single_question(assistant_content_for_chat)
          or _violates_answered_fields(assistant_content_for_chat, draft_state)
          or _violates_recent_answer(assistant_content_for_chat, pending_question_key, user_message)
          or _violates_classification_exposure(assistant_content_for_chat, chat_support_data)
          or _violates_missing_summary(assistant_content_for_chat, user_message, chat_support_data)
          or _violates_no_confirmation(assistant_content_for_chat, chat_support_data)
          or needs_question
        ):
          break
        _log_event(app, event="conversation_retry", draft_id=draft_id)
        llm_started = time.time()
        try:
          retry_support_data = dict(support_data)
          for key in (
            "force_patch_only",
            "force_patch_target",
            "force_patch_reason",
            "validation_error",
            "invalid_patch",
          ):
            retry_support_data.pop(key, None)
          retry_support_data["conversation_only"] = True
          retry_support_data["no_classification_exposure"] = True
          if patch_target or _requires_question(draft_state):
            retry_support_data["require_question"] = True
          if chat_support_data.get("force_business_summary"):
            retry_support_data["validation_error"] = "missing_business_summary"
          assistant_content_for_chat = _call_llm(
            messages_json=messages_json,
            draft_state=draft_state,
            user_message=user_message,
            support_data=retry_support_data,
          )
          chat_support_data = dict(retry_support_data)
        finally:
          duration_ms = int((time.time() - llm_started) * 1000)
          _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="conversation_retry")
        if _violates_classification_exposure(assistant_content_for_chat, chat_support_data):
          assistant_content_for_chat = _sanitize_classification_exposure(assistant_content_for_chat, chat_support_data)
        attempts += 1
      needs_question = bool(chat_support_data.get("require_question") or _requires_question(draft_state))
      needs_question = needs_question and "?" not in assistant_content_for_chat
      violates_single = _violates_single_question(assistant_content_for_chat)
      if (
        violates_single
        or _violates_answered_fields(assistant_content_for_chat, draft_state)
        or _violates_recent_answer(assistant_content_for_chat, pending_question_key, user_message)
        or _violates_missing_summary(assistant_content_for_chat, user_message, chat_support_data)
        or _violates_no_confirmation(assistant_content_for_chat, chat_support_data)
        or needs_question
      ):
        if violates_single and not chat_support_data.get("force_business_summary"):
          fallback_prompt = str(chat_support_data.get("current_field_prompt") or "").strip()
          if fallback_prompt:
            assistant_content_for_chat = f"{fallback_prompt.rstrip('?')}?"
          else:
            assistant_content_for_chat = _sanitize_single_question(assistant_content_for_chat)
        else:
          assistant_content_for_chat = _sanitize_single_question(assistant_content_for_chat)
      if chat_support_data.get("no_confirmation") and _violates_no_confirmation(
        assistant_content_for_chat, chat_support_data
      ):
        fallback_prompt = str(chat_support_data.get("current_field_prompt") or "").strip()
        if fallback_prompt:
          assistant_content_for_chat = f"{fallback_prompt.rstrip('?')}?"
      if chat_support_data.get("require_question") and not _question_mentions_current_field(
        assistant_content_for_chat, chat_support_data
      ):
        fallback_prompt = str(chat_support_data.get("current_field_prompt") or "").strip()
        if fallback_prompt:
          assistant_content_for_chat = f"{fallback_prompt.rstrip('?')}?"

    if _is_valid_patch_message(assistant_content_for_chat):
      attempts = 0
      while _is_valid_patch_message(assistant_content_for_chat) and attempts < MAX_CONVERSATION_ATTEMPTS:
        _log_event(app, event="conversation_retry", draft_id=draft_id)
        llm_started = time.time()
        try:
          retry_support_data = dict(support_data)
          for key in (
            "force_patch_only",
            "force_patch_target",
            "force_patch_reason",
            "validation_error",
            "invalid_patch",
          ):
            retry_support_data.pop(key, None)
          retry_support_data["conversation_only"] = True
          retry_support_data["no_classification_exposure"] = True
          if _requires_question(draft_state):
            retry_support_data["require_question"] = True
          assistant_content_for_chat = _call_llm(
            messages_json=messages_json,
            draft_state=draft_state,
            user_message="continue",
            support_data=retry_support_data,
          )
          chat_support_data = dict(retry_support_data)
        finally:
          duration_ms = int((time.time() - llm_started) * 1000)
          _log_event(app, event="llm_call_end", draft_id=draft_id, duration_ms=duration_ms, phase="conversation_retry")
        attempts += 1

    new_messages: List[Dict[str, str]] = []
    if user_message.strip():
      new_messages.append({"role": "user", "content": user_message})
    if assistant_content_for_chat.strip():
      new_messages.append({"role": "assistant", "content": assistant_content_for_chat})
    if new_messages:
      append_messages(conn, draft_id=draft_id, new_messages=new_messages)

    effective_field_key = str(chat_support_data.get("current_field_key") or current_field_key).strip()
    if assistant_content_for_chat.strip() and not _is_valid_patch_message(assistant_content_for_chat):
      if "?" in assistant_content_for_chat and effective_field_key:
        pending_key = effective_field_key
        pending_kind = "confirm" if (
          chat_support_data.get("require_confirmation") or _looks_like_confirmation(assistant_content_for_chat)
        ) else "ask"
      else:
        pending_key = None
        pending_kind = None
      update_draft(
        conn,
        draft_id=draft_id,
        updates={"pending_question_key": pending_key, "pending_question_kind": pending_kind},
      )

    assistant_is_patch = _is_valid_patch_message(assistant_content_for_chat)
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft_id,
        "assistant_message": assistant_content_for_chat,
        "assistant_is_patch": assistant_is_patch,
        "active_focus": _focus_token(patch_target) if patch_target else str(draft.get("active_focus") or ""),
      }
    )
  except Exception as exc:
    app.logger.exception("Failed to run consult: %s", exc)
    return jsonify({"error": "server_error", "detail": str(exc)}), 500
  finally:
    try:
      conn.close()
    except Exception:
      pass
