from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
FINALIZE_TOKEN = "[[FINALIZE_READY]]"
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


def _openai_timeout_seconds() -> int:
  _load_root_env()
  raw = (os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS") or "").strip()
  if raw:
    try:
      return max(30, int(raw))
    except Exception:
      return 180
  return 180


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


def _parse_responses_text(data: Dict[str, Any]) -> str:
  output = data.get("output") or []
  chunks: list[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        chunks.append(str(part["text"]))
  if not chunks:
    raise RuntimeError("OpenAI response contained no output_text.")
  return "\n".join(chunks).strip()


def _parse_responses_json(data: Dict[str, Any]) -> Dict[str, Any]:
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      parsed = part.get("parsed")
      if isinstance(parsed, dict):
        return parsed
      if part.get("type") == "output_text" and part.get("text"):
        try:
          parsed_text = json.loads(str(part.get("text") or "").strip())
        except Exception:
          continue
        if isinstance(parsed_text, dict):
          return parsed_text
  raise RuntimeError("OpenAI response contained no parsed JSON.")


def _revenue_adjudication_schema() -> Dict[str, Any]:
  return {
    "name": "financials_revenue_adjudication",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "requires_adjustment": {"type": "boolean"},
        "good_to_proceed_without_revenue_change": {"type": "boolean"},
        "overall_judgment": {"type": "string"},
        "dominant_constraint": {"type": "string"},
        "plain_language_summary": {"type": "string"},
        "proceed_rationale": {"type": "string"},
        "options": {
          "type": "array",
          "maxItems": 4,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "option_id": {"type": "string"},
              "label": {"type": "string"},
              "suggested_change": {"type": "string"},
              "why_it_helps": {"type": "string"},
              "driver_changes": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                  "financials_year1_patch": {
                    "type": "object",
                    "additionalProperties": True,
                  },
                  "financials_patch": {
                    "type": "object",
                    "additionalProperties": True,
                  },
                },
                "required": ["financials_year1_patch", "financials_patch"],
              },
            },
            "required": [
              "option_id",
              "label",
              "suggested_change",
              "why_it_helps",
              "driver_changes",
            ],
          },
        },
      },
      "required": [
        "requires_adjustment",
        "good_to_proceed_without_revenue_change",
        "overall_judgment",
        "dominant_constraint",
        "plain_language_summary",
        "proceed_rationale",
        "options",
      ],
    },
  }


def _build_revenue_adjudication_context(intake_context: Dict[str, Any]) -> Dict[str, Any]:
  shared_context = intake_context.get("shared_context")
  if not isinstance(shared_context, dict):
    shared_context = {}

  operating_model = shared_context.get("operating_model")
  if not isinstance(operating_model, dict):
    operating_model = {}
  market_context = shared_context.get("target_market")
  if not isinstance(market_context, dict):
    market_context = {}
  people_context = shared_context.get("people_capability")
  if not isinstance(people_context, dict):
    people_context = {}
  fulfillment_context = intake_context.get("fulfillment_json")
  if not isinstance(fulfillment_context, dict):
    fulfillment_context = {}

  people_summary = []
  for person in people_context.get("people") or []:
    if not isinstance(person, dict):
      continue
    people_summary.append(
      {
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "experience_years": str(person.get("experience_years") or "").strip(),
        "annual_wage": person.get("annual_wage"),
      }
    )

  inferred_roles_summary = []
  for role in people_context.get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    inferred_roles_summary.append(
      {
        "role_title": str(role.get("role_title") or "").strip(),
        "annual_wage": role.get("annual_wage"),
        "months_until_hire": role.get("months_until_hire"),
      }
    )

  return {
    "business": {
      "name": intake_context.get("business_name"),
      "start_date": intake_context.get("business_start_date"),
    },
    "ops": {
      "business_type": operating_model.get("business_type"),
      "business_description_summary": operating_model.get("business_description_summary"),
      "business_stage": operating_model.get("business_stage"),
      "consumer_type": operating_model.get("consumer_type"),
      "sales_modality": operating_model.get("sales_modality"),
      "shipping_method": operating_model.get("shipping_method"),
      "geographic_scope": operating_model.get("geographic_scope"),
      "geographic_coverage": operating_model.get("geographic_coverage"),
      "capacity_driver": operating_model.get("capacity_driver"),
      "primary_growth_lever": operating_model.get("primary_growth_lever"),
      "legal_entity": operating_model.get("legal_entity"),
      "competitive_advantage": operating_model.get("competitive_advantage"),
      "milestones": operating_model.get("milestones"),
    },
    "market": {
      "consumer_type": market_context.get("consumer_type"),
      "target_market_summary": market_context.get("target_market_summary"),
      "marketing_plan_summary": market_context.get("marketing_plan_summary"),
    },
    "people": {
      "people": people_summary,
      "inferred_roles": inferred_roles_summary,
      "key_people_summary": people_context.get("key_people_summary"),
    },
    "fulfillment": {
      "time": fulfillment_context.get("time"),
      "personnel": fulfillment_context.get("personnel"),
    },
    "revenue_model": intake_context.get("financials_year1_json") or {},
    "guardrail_context_signals": intake_context.get("revenue_guardrail_context_signals") or [],
    "guardrail_product_signals": intake_context.get("revenue_guardrail_product_signals") or [],
  }


def _adjudicate_revenue_setup(intake_context: Dict[str, Any]) -> Dict[str, Any]:
  financials_year1_json = intake_context.get("financials_year1_json")
  if not isinstance(financials_year1_json, dict) or not financials_year1_json:
    return {}

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _revenue_adjudication_schema()
  context_blob = json.dumps(_build_revenue_adjudication_context(intake_context), ensure_ascii=False)

  system = """
You are adjudicating whether a Year-1 revenue setup is internally coherent for a business plan.

Your job:
- Judge the revenue setup holistically using the provided persisted context.
- Use business type/industry, stage/start date, product mix, capacity, utilization, price, periods/year, people/wages, hiring timing, fulfillment reality, target market, and operational constraints together.
- Treat practical capacity as the ceiling and utilization as the planned Year-1 operating level. Do not silently convert the setup into a 100% utilization assumption unless the context explicitly does that.
- Do NOT use hardcoded utilization bands, canned industry templates, or external benchmarks.
- Decide whether the Year-1 revenue setup is workable as-is, too stretched, too low for the stated model, or structurally inconsistent.

Adjustment options:
- If no revenue change is needed, set requires_adjustment to false, good_to_proceed_without_revenue_change to true, and return options as an empty list.
- If revenue does need adjustment, set requires_adjustment to true and return 2 to 4 concrete options.
- Each option must be short, client-friendly, and include deterministic driver_changes.
- Each option must contain explicit changed values and a matching driver_changes object.
- driver_changes.financials_year1_patch should carry the exact revenue-driver patch to apply.
- driver_changes.financials_patch may carry supporting financial assumption changes (for example payroll, owner pay, rent, or regular operating costs) when needed to make the overall model coherent.
- Each option must be a complete resolution path, not a partial tweak that requires another revenue-adjustment round afterward.

Output intent:
- plain_language_summary should be one concise, non-technical paragraph for the client.
- proceed_rationale should be a short explanation of why the current setup can proceed unchanged when good_to_proceed_without_revenue_change is true; otherwise explain the main tension.
- dominant_constraint should name the main bottleneck or "none" if there is no meaningful strain.
- The reasoning must be holistic. Do not reduce the judgment to capacity/utilization alone if the broader business context materially affects feasibility.
""".strip()

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

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return {}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {}
  if isinstance(parsed, dict) and bool(parsed.get("requires_adjustment")):
    options = parsed.get("options")
    if not isinstance(options, list) or len(options) < 2:
      payload["input"] = [
        {
          "role": "system",
          "content": system + "\nSTRICT MODE: if adjustment is required, you MUST return at least 2 and at most 4 complete options.",
        },
        {"role": "user", "content": context_blob},
      ]
      resp = _post_openai(url=url, headers=headers, payload=payload)
      if resp.status_code < 400:
        try:
          parsed = _parse_responses_json(resp.json())
        except Exception:
          pass
  return parsed if isinstance(parsed, dict) else {}


def _locked_revenue_adjudication(intake_context: Dict[str, Any]) -> Dict[str, Any]:
  financials_json = intake_context.get("financials_json")
  if not isinstance(financials_json, dict):
    financials_json = {}
  financials_year1_json = intake_context.get("financials_year1_json")
  if not isinstance(financials_year1_json, dict) or not financials_year1_json:
    return {}
  try:
    from financials_year1 import build_revenue_driver_signature  # type: ignore
  except Exception:
    try:
      from client_intake_and_finmo.financials_year1 import build_revenue_driver_signature  # type: ignore
    except Exception:
      return {}

  locked_signature = str(financials_json.get("_revenue_adjustment_locked_signature") or "").strip()
  current_signature = str(build_revenue_driver_signature(financials_year1_json) or "").strip()
  if not locked_signature or not current_signature or locked_signature != current_signature:
    return {}

  locked_summary = str(financials_json.get("_revenue_adjustment_locked_summary") or "").strip()
  if not locked_summary:
    locked_summary = (
      "This revised revenue setup is now the locked Year-1 baseline for the rest of the "
      "financial model, and it is consistent enough to proceed without reopening the same "
      "revenue adjustment issue."
    )

  return {
    "requires_adjustment": False,
    "good_to_proceed_without_revenue_change": True,
    "overall_judgment": "locked_baseline",
    "dominant_constraint": "none",
    "plain_language_summary": locked_summary,
    "proceed_rationale": locked_summary,
    "options": [],
  }


def _cogs_reply_schema() -> Dict[str, Any]:
  return {
    "name": "financials_cogs_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": [
            "accept_baseline",
            "set_total",
            "set_monthly_amount",
            "set_percent",
            "set_adjustment",
            "ask_question",
            "unclear",
          ],
        },
        "cogs_total_year1": {"type": ["number", "null"]},
        "cogs_monthly_amount": {"type": ["number", "null"]},
        "cogs_percent_of_revenue": {"type": ["number", "null"]},
        "cogs_adjustment": {"type": ["number", "null"]},
        "question_or_clarification": {"type": "string"},
      },
      "required": [
        "intent_type",
        "cogs_total_year1",
        "cogs_monthly_amount",
        "cogs_percent_of_revenue",
        "cogs_adjustment",
        "question_or_clarification",
      ],
    },
  }


def interpret_cogs_reply(
  *,
  user_message: str,
  last_assistant: str,
  cogs_context: Dict[str, Any],
) -> Dict[str, Any]:
  if not str(user_message or "").strip():
    return {}

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _cogs_reply_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply to a Year-1 COGS stage in an intake consult.\n"
          "Sometimes there is an industry baseline proposal. Sometimes there is no benchmark and the client is being asked for a Year-1 direct-cost assumption.\n"
          "Classify whether the client accepts the baseline, sets a new total annual COGS amount, gives a monthly direct-cost amount, gives a COGS percent of revenue, gives an additive adjustment from baseline, asks a question, or is unclear.\n"
          "Do not rely on exact keywords. Use the assistant proposal, the numeric baseline context, and the user's reply together.\n"
          "If the user asks a question or is unclear, put the follow-up text in question_or_clarification.\n"
          "For set_percent, return the percent as a decimal fraction when clear (for example 0.42 for 42%).\n"
          "For set_monthly_amount, return the monthly amount only; do not annualize it yourself."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": str(last_assistant or "").strip(),
            "cogs_context": cogs_context,
            "user_message": str(user_message or "").strip(),
          },
          ensure_ascii=False,
        ),
      },
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
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return {}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _cogs_validation_schema() -> Dict[str, Any]:
  return {
    "name": "financials_cogs_validation",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "proceed": {"type": "boolean"},
        "assistant_message": {"type": "string"},
      },
      "required": ["proceed", "assistant_message"],
    },
  }


def validate_cogs_setup(
  *,
  intake_context: Dict[str, Any],
  cogs_context: Dict[str, Any],
  user_message: str,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _cogs_validation_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are validating a proposed Year-1 COGS setup for an intake consult.\n"
          "Sometimes the COGS baseline comes from industry data; sometimes no benchmark is available and the client provides the Year-1 direct-cost assumption directly.\n"
          "Decide whether the resulting Year-1 direct-cost setup is coherent enough to proceed.\n"
          "Use the business type, revenue, operating model, and the final COGS percent/total.\n"
          "If it is coherent enough for intake, set proceed=true and return a very short acknowledgement or an empty string.\n"
          "If it likely misses major direct costs or is structurally inconsistent, set proceed=false and ask one short clarification question.\n"
          "Do not ask the client to build COGS from scratch.\n"
          "Do not rely on exact keywords."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "intake_context": intake_context,
            "cogs_context": cogs_context,
            "user_message": str(user_message or "").strip(),
          },
          ensure_ascii=False,
        ),
      },
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
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return {"proceed": True, "assistant_message": ""}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {"proceed": True, "assistant_message": ""}
  return parsed if isinstance(parsed, dict) else {"proceed": True, "assistant_message": ""}


def _payroll_reply_schema() -> Dict[str, Any]:
  return {
    "name": "financials_payroll_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": [
            "accept_baseline",
            "set_total",
            "set_adjustment",
            "ask_question",
            "unclear",
          ],
        },
        "payroll_total_year1": {"type": ["number", "null"]},
        "payroll_adjustment": {"type": ["number", "null"]},
        "question_or_clarification": {"type": "string"},
      },
      "required": [
        "intent_type",
        "payroll_total_year1",
        "payroll_adjustment",
        "question_or_clarification",
      ],
    },
  }


def interpret_payroll_reply(
  *,
  user_message: str,
  last_assistant: str,
  payroll_context: Dict[str, Any],
) -> Dict[str, Any]:
  if not str(user_message or "").strip():
    return {}

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _payroll_reply_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply to a Year-1 payroll baseline proposal.\n"
          "The baseline payroll has already been computed deterministically from the People plan.\n"
          "Classify whether the client accepts the baseline, sets a new total annual payroll amount, gives an additive adjustment from baseline, asks a question, or is unclear.\n"
          "Do not rely on exact keywords. Use the assistant proposal, the numeric baseline context, and the user's reply together.\n"
          "If the user asks a question or is unclear, put the follow-up text in question_or_clarification."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": str(last_assistant or "").strip(),
            "payroll_context": payroll_context,
            "user_message": str(user_message or "").strip(),
          },
          ensure_ascii=False,
        ),
      },
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
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return {}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _payroll_validation_schema() -> Dict[str, Any]:
  return {
    "name": "financials_payroll_validation",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "proceed": {"type": "boolean"},
        "assistant_message": {"type": "string"},
      },
      "required": ["proceed", "assistant_message"],
    },
  }


def validate_payroll_setup(
  *,
  intake_context: Dict[str, Any],
  payroll_context: Dict[str, Any],
  user_message: str,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _payroll_validation_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are validating a proposed Year-1 payroll setup for an intake consult.\n"
          "The baseline payroll came from the People plan and the client may have accepted it or adjusted it.\n"
          "Decide whether the resulting Year-1 payroll setup is coherent enough to proceed.\n"
          "Use the business type, revenue, staffing plan, hiring timing, and final payroll total.\n"
          "If it is coherent enough for intake, set proceed=true and return a very short acknowledgement or an empty string.\n"
          "If it likely conflicts with the people plan or the broader business setup, set proceed=false and ask one short clarification question.\n"
          "Do not ask the client to rebuild payroll from scratch.\n"
          "Do not rely on exact keywords."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "intake_context": intake_context,
            "payroll_context": payroll_context,
            "user_message": str(user_message or "").strip(),
          },
          ensure_ascii=False,
        ),
      },
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
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return {"proceed": True, "assistant_message": ""}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {"proceed": True, "assistant_message": ""}
  return parsed if isinstance(parsed, dict) else {"proceed": True, "assistant_message": ""}


def _initial_lease_reply_schema() -> Dict[str, Any]:
  return {
    "name": "financials_initial_lease_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": ["set_none", "set_value", "ask_question", "unclear"],
        },
        "payment_amount": {"type": ["number", "null"]},
        "period": {
          "type": ["string", "null"],
          "enum": [None, "daily", "weekly", "monthly", "quarterly", "yearly", "annual", "one-time", "unknown", "none"],
        },
        "question_or_clarification": {"type": "string"},
      },
      "required": ["intent_type", "payment_amount", "period", "question_or_clarification"],
    },
  }


def interpret_initial_lease_reply(
  *,
  user_message: str,
  last_assistant: str,
) -> Dict[str, Any]:
  if not str(user_message or "").strip():
    return {}

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _initial_lease_reply_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply about leased or rented equipment/space costs beyond main rent.\n"
          "Classify whether the client says there is no such lease cost, provides a payment amount and frequency, asks a question, or is unclear.\n"
          "Do not rely on exact keywords. Use the assistant question and the user's reply together.\n"
          "If there is no such lease cost, return intent_type='set_none'.\n"
          "If there is a lease cost, return intent_type='set_value' with payment_amount and period.\n"
          "Normalize period to one of: daily, weekly, monthly, quarterly, yearly, annual, one-time, unknown.\n"
          "If the user asks a question or is unclear, put the follow-up text in question_or_clarification."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": str(last_assistant or "").strip(),
            "user_message": str(user_message or "").strip(),
          },
          ensure_ascii=False,
        ),
      },
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
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return {}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _revenue_option_reply_schema() -> Dict[str, Any]:
  return {
    "name": "financials_revenue_option_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": ["select_option", "custom_change", "ask_question", "reject_all", "unclear"],
        },
        "selected_option_id": {
          "type": ["string", "null"],
        },
        "reason": {"type": "string"},
      },
      "required": ["intent_type", "selected_option_id", "reason"],
    },
  }


def interpret_revenue_option_reply(
  *,
  user_message: str,
  last_assistant: str,
  pending_options: List[Dict[str, Any]],
) -> Dict[str, Any]:
  if not str(user_message or "").strip():
    return {}
  options = [option for option in (pending_options or []) if isinstance(option, dict)]
  if not options:
    return {}

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _revenue_option_reply_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply to a Financials revenue-adjustment turn.\n"
          "Classify whether the client selected one of the previously proposed options, "
          "proposed a custom change instead, asked a question, rejected all options, or was unclear.\n"
          "Use the stored structured options and the visible assistant wording as context.\n"
          "Do not rely on exact keywords. Only return select_option when the user's meaning clearly chooses one of the provided options."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": str(last_assistant or "").strip(),
            "pending_options": options,
            "user_message": str(user_message or "").strip(),
          },
          ensure_ascii=False,
        ),
      },
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

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return {}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _split_revenue_table_block(text: str) -> Tuple[str, str]:
  raw = str(text or "").strip()
  if "Year 1 revenue:" not in raw:
    return raw, ""
  marker = "Year 1 revenue:"
  start = raw.find(marker)
  table_start = raw.find("\n\n", start)
  if table_start == -1:
    return raw, ""
  remainder_start = raw.find("\n\n", table_start + 2)
  if remainder_start == -1:
    return raw, ""
  return raw[:remainder_start].strip(), raw[remainder_start:].strip()


def _extract_last_question(text: str) -> str:
  raw = str(text or "").strip()
  if not raw:
    return ""
  lines = [line.strip() for line in raw.splitlines() if line.strip()]
  for line in reversed(lines):
    if line.endswith("?"):
      return line
  return ""


def _render_revenue_adjudication_response(
  *,
  draft_text: str,
  intake_context: Dict[str, Any],
) -> str:
  adjudication = intake_context.get("revenue_adjudication")
  if not isinstance(adjudication, dict) or not adjudication:
    return draft_text

  table_block, remainder = _split_revenue_table_block(draft_text)
  if "Year 1 revenue:" not in table_block:
    return draft_text

  plain_summary = str(adjudication.get("plain_language_summary") or "").strip()
  proceed_rationale = str(adjudication.get("proceed_rationale") or "").strip()
  requires_adjustment = bool(adjudication.get("requires_adjustment"))
  can_proceed = bool(adjudication.get("good_to_proceed_without_revenue_change"))
  options = adjudication.get("options")
  options = options if isinstance(options, list) else []

  body_parts: List[str] = []
  if plain_summary:
    body_parts.append(plain_summary)
  elif proceed_rationale:
    body_parts.append(proceed_rationale)

  if requires_adjustment:
    option_lines: List[str] = []
    for idx, option in enumerate(options[:4], start=1):
      if not isinstance(option, dict):
        continue
      suggested_change = str(option.get("suggested_change") or "").strip()
      why_it_helps = str(option.get("why_it_helps") or "").strip()
      label = f"Option {idx}: {suggested_change}".strip()
      if why_it_helps:
        label = f"{label} - {why_it_helps}"
      option_lines.append(f"- {label}")
    if option_lines:
      body_parts.append("\n".join(option_lines))
    body_parts.append("Which option do you want, or what else do you want to change?")
  elif can_proceed:
    next_question = _extract_last_question(remainder)
    if next_question:
      body_parts.append(next_question)
    elif proceed_rationale and proceed_rationale not in body_parts:
      body_parts.append(proceed_rationale)

  if not body_parts:
    return draft_text

  return f"{table_block}\n\n" + "\n\n".join(part for part in body_parts if part.strip())


def _normalize_cadence(value: Any) -> str:
  raw = str(value or "").strip().lower()
  if raw in ("monthly", "month", "per month", "mo", "m"):
    return "monthly"
  if raw in ("contract", "retainer", "case", "engagement", "project"):
    return "contract"
  return "weekly"


def _extract_cadences(financials_year1_json: Dict[str, Any]) -> List[str]:
  cadences: List[str] = []
  lobs = financials_year1_json.get("lobs")
  if isinstance(lobs, list):
    for lob in lobs:
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product in products:
        if not isinstance(product, dict):
          continue
        cadences.append(_normalize_cadence(product.get("unit_cadence")))
  else:
    cadences.append(_normalize_cadence(financials_year1_json.get("unit_cadence")))
  return [c for c in cadences if c]


def _is_time_slice_forbidden(text: str, cadences: List[str]) -> bool:
  if not cadences:
    return False
  monthly_only = all(c == "monthly" for c in cadences)
  if monthly_only:
    return False
  lowered = text.lower()
  if re.search(r"\b12\s+months?\b", lowered):
    return True
  if re.search(r"\b12\s+periods?\b", lowered):
    return True
  return False


def _has_required_revenue_elements(
  *,
  text: str,
  guardrail_triggered: bool,
  intake_context: Dict[str, Any],
) -> bool:
  lowered = text.lower()
  adjudication = intake_context.get("revenue_adjudication")
  if not isinstance(adjudication, dict):
    adjudication = {}

  has_constraint_language = any(
    token in lowered
    for token in (
      "utilization",
      "capacity",
      "demand",
      "staff",
      "team",
      "hiring",
      "ramp",
      "timing",
      "volume",
      "price",
    )
  )
  has_question = text.count("?") == 1
  has_options = "option 1" in lowered or "- option 1" in lowered
  full_capacity_claim = ("full capacity" in lowered or "fully booked" in lowered)

  financials_year1_json = intake_context.get("financials_year1_json")
  if not isinstance(financials_year1_json, dict):
    financials_year1_json = {}
  utilization_below_full = False
  lobs = financials_year1_json.get("lobs")
  if isinstance(lobs, list):
    for lob in lobs:
      if not isinstance(lob, dict):
        continue
      for product in lob.get("products") or []:
        if not isinstance(product, dict):
          continue
        try:
          utilization = float(product.get("utilization_rate"))
        except Exception:
          utilization = None
        if utilization is not None and utilization < 0.999:
          utilization_below_full = True
          break
      if utilization_below_full:
        break

  if utilization_below_full and full_capacity_claim:
    return False

  if guardrail_triggered and not any(
    token in lowered for token in ("strain", "pressure", "risk", "tight", "constraint")
  ):
    return False

  requires_adjustment = bool(adjudication.get("requires_adjustment"))
  can_proceed = bool(adjudication.get("good_to_proceed_without_revenue_change"))

  if not has_constraint_language or not has_question:
    return False
  if requires_adjustment and not has_options:
    return False
  if can_proceed and has_options:
    return False
  return True


def _needs_revenue_rewrite(
  *,
  text: str,
  intake_context: Dict[str, Any],
) -> bool:
  if "Year 1 revenue" not in text:
    return False
  financials_year1_json = intake_context.get("financials_year1_json")
  if not isinstance(financials_year1_json, dict):
    financials_year1_json = {}
  cadences = _extract_cadences(financials_year1_json)
  if _is_time_slice_forbidden(text, cadences):
    return True
  guardrail_triggered = bool(intake_context.get("revenue_guardrail_triggered"))
  if not _has_required_revenue_elements(
    text=text,
    guardrail_triggered=guardrail_triggered,
    intake_context=intake_context,
  ):
    return True
  return False


def _rewrite_financials_revenue_response(
  *,
  draft_text: str,
  intake_context: Dict[str, Any],
) -> str:
  if "Year 1 revenue" not in draft_text:
    return draft_text
  adjudication = intake_context.get("revenue_adjudication")
  if isinstance(adjudication, dict) and adjudication:
    rendered = _render_revenue_adjudication_response(
      draft_text=draft_text,
      intake_context=intake_context,
    )
    if not _needs_revenue_rewrite(text=rendered, intake_context=intake_context):
      return rendered
  if not _needs_revenue_rewrite(text=draft_text, intake_context=intake_context):
    return draft_text

  api_key = _require_openai_key()
  model = _openai_model()

  system = """
You are a compliance editor for a Financials Year-1 revenue response.

Rules:
- Keep the existing "Year 1 revenue:" header and the revenue table exactly intact.
- Replace only the client-facing narrative and question beneath the table.
- Use the provided revenue_adjudication object as the source of truth for the judgment. Do not contradict it.
- Judge the setup holistically: business type/industry, stage/start date, capacity, utilization, price, periods/year, staffing/wages, hiring timing, fulfillment, and other persisted constraints.
- Treat utilization as the planned Year-1 operating level. Do not describe the setup as full capacity or fully booked unless utilization is actually 100%.
- The narrative must be one concise paragraph in plain English for a non-financial client.
- If revenue_adjudication.good_to_proceed_without_revenue_change is true:
  - do NOT offer options,
  - do NOT ask for permission to proceed on revenue,
  - stop after the revenue explanation.
- If revenue_adjudication.requires_adjustment is true:
  - include 2 to 4 short option bullets labeled "Option 1", "Option 2", "Option 3", and optionally "Option 4",
  - each option must contain a concrete changed value tied to the revenue-driver model,
  - each option must be a complete resolution path, not a partial tweak that forces another revenue-adjustment round,
  - end with one question asking which option they want or what else they want to change.
- If revenue_adjudication.good_to_proceed_without_revenue_change is true because the revenue baseline is already locked, acknowledge that locked baseline once and stop after the revenue explanation.
- Keep the tone decisive and client-friendly. No hedging, no generic filler.
- Do not introduce new facts, benchmarks, or external data.
- Do not rely on canned "aggressive/conservative/balanced" wording unless it genuinely fits the adjudication.

If the draft already complies, return it unchanged. Otherwise, rewrite it to comply.
Return ONLY the final response text.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  user = (
    "Context JSON:\n"
    f"{context_blob}\n\n"
    "Draft response:\n"
    f"{draft_text}\n\n"
    "Return the final response:"
  )

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": user},
    ],
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return draft_text

  try:
    revised = _parse_responses_text(resp.json())
  except Exception:
    return draft_text

  revised = revised or draft_text
  if not _needs_revenue_rewrite(text=revised, intake_context=intake_context):
    return revised

  # One more pass with stricter enforcement if needed.
  system_strict = (
    system
    + "\n"
    + "STRICT MODE: You MUST preserve the table exactly, use 2 to 4 option bullets when adjustment is needed, "
    + "and never describe sub-100% utilization as full capacity."
  )
  payload["input"] = [
    {"role": "system", "content": system_strict},
    {"role": "user", "content": user},
  ]
  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    return revised
  try:
    revised_strict = _parse_responses_text(resp.json())
  except Exception:
    return revised
  return revised_strict or revised


def _final_schema() -> Dict[str, Any]:
  return {
    "name": "intake_financials_final",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
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
        "initial_assets": {"type": "number"},
        "initial_lease": {"type": "string"},
        "initial_equity": {"type": "number"},
        "total_debt_outstanding": {"type": "number"},
        "annual_interest_payment": {"type": "number"},
        "annual_principal_payment": {"type": "number"},
        "owner_compensation": {"type": "number"},
        "cash_on_hand": {"type": "number"},
        "confidence": {"type": "number"},
      },
      "required": [
        "financials_summary",
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
        "initial_assets",
        "initial_lease",
        "initial_equity",
        "total_debt_outstanding",
        "annual_interest_payment",
        "annual_principal_payment",
        "owner_compensation",
        "cash_on_hand",
        "confidence",
      ],
    },
  }


def financials_chat_turn(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  Free-text Financials consultant conversation turn (NO schema enforcement).

  Returns:
    { "assistant_message": str, "finalize_ready": bool }
  """
  api_key = _require_openai_key()
  model = _openai_model()
  active_stage = str(intake_context.get("financials_active_stage") or "").strip()
  revenue_adjudication = _locked_revenue_adjudication(intake_context) or _adjudicate_revenue_setup(intake_context)
  if revenue_adjudication:
    intake_context = dict(intake_context)
    intake_context["revenue_adjudication"] = revenue_adjudication

  system = f"""
You are a business consultant running the Financials intake conversation.

Goal:
- Capture the remaining financial picture needed for intake.
- current_revenue and current_cogs are modeled Year-1 values when they are already present in context; do not re-ask them as historical memory questions.
- Ask one question at a time and keep it non-overwhelming.
- Behave like a human consultant: infer intent, keep it conversational, and avoid rigid command-style prompts.

Senior consultant lens (LIGHT plausibility checks; Consistency is the final arbitrator):
- Treat the outputs of Ops, People, and Market as fixed reality inputs provided in the context JSON (often under shared_context). Do not re-run intake, do not re-explain the business, and do not ask the client to reconfirm upstream facts.
- Use those upstream facts to do gentle feasibility checks and flag obvious contradictions (not precision accounting).
- When a number clearly does not fit upstream reality, ask ONE targeted clarifying question; you MAY suggest a corrected value (or tight range) as a proposal.
- If the client agrees to a correction, record it and continue.
- If the client rejects the correction or it remains unclear after minimal clarification, record the client's number as provisional and keep going; Consistency will arbitrate cross-domain contradictions later.

Core rule for this section:
- Do not ask the client to choose or label a time basis. Use the anchor "as of last month".
- Anchor everything to "as of last month". If the client doesn't have the item, explicitly tell them you're recording 0 and move on.
- Nothing should be left unknown: if you can't get a clear answer after minimal clarification, record 0 and move on.
- Exception: current_revenue, current_cogs, and current_payroll are controller-owned modeled Year-1 values when already present. Treat them as established and move to the next unanswered item.

Style:
- One plain question sentence per message.
- Optional short bullet choices under it (not numbered).
- Explain each item in everyday terms (assume no finance background).
- Only ask for a number if the client actually has the item as of last month.
- If the client says "no", "none", "not yet", or they don't know after brief clarification, record 0 and explicitly say so.
- If they give a range, ask for one best number. If they give formatted strings ($, commas, "k"), interpret them into a number.
- Ask the minimum number of clarifying questions needed to reconcile economic reality, then stop. Usually 0-1; occasionally 2; never a chain.
- Use information from other consults only to reconcile reality (not to debate or forecast).

Revenue assembly (REPLACES revenue question):
- You will be given financials_year1_json and revenue_math_line in the context JSON.
- Start this section by presenting "Year 1 revenue:" followed by a blank line, then include the revenue_math_line verbatim.
- Revenue is derived at the product level; LOB totals are rollups only.
- Explain the result in plain English using the full persisted business context, especially business type/industry, stage/start date, capacity, utilization, price, periods/year, staffing/wages, hiring timing, fulfillment, and the other constraints already captured in Ops/Market/People.
- Do NOT ask "What is your revenue?" and do NOT ask for a revenue number.
- If revenue_driver_patch is present in context, acknowledge the change and re-state the updated revenue_math_line before moving on.
- If revenue_adjudication is present in context, follow it. It is the holistic revenue judgment for this exact Year-1 setup.

COGS handling (controller-owned):
- COGS is always a controller-owned Year-1 modeled stage.
- Do not ask a COGS/direct-cost question in the generic Financials flow.
- If current_cogs or cogs_total_year1 is already present in context, treat Year-1 direct costs as established and move on.

Payroll handling (REPLACES payroll question when already present):
- If current_payroll or payroll_total_year1 is already present in context, treat Year-1 payroll as established.
- Do not ask a monthly or historical payroll question once that Year-1 payroll value exists.

Stage control:
- The controller may provide financials_active_stage in the context.
- If financials_active_stage is present, you must handle ONLY that one stage and nothing else.
- Do not skip ahead, do not bundle later financial topics, and do not ask about a different stage.
- If financials_active_stage is "revenue_intro" and revenue does not need adjustment, explain the revenue setup only and stop; the controller will advance to the next stage.
- If financials_active_stage is "cogs", do not ask a COGS question here; the controller owns that stage.
- If financials_active_stage is "current_payroll", do not ask a payroll question here; the controller owns that stage.
- If financials_active_stage is "initial_lease", do not ask a lease question here; the controller owns that stage.
- For other stages, ask exactly one question for that stage only.

Stage names:
- revenue_intro
- cogs
- current_payroll
- other_operating_expense
- monthly_rent_expense
- owner_compensation
- current_num_employees
- current_capex
- initial_assets
- initial_lease
- initial_equity
- total_debt_outstanding
- other_monthly_debt_payments
- annual_interest_payment
- annual_principal_payment
- cash_on_hand
- ar_balance
- ap_balance
- inventory_balance

Financials adjudication (MANDATORY):
- You are an arbitrator, not an interviewer. Take a position, state implications plainly, then ask for agreement or correction.
- Do not use hedging phrases like "Does this feel right?", "If you'd like, we can...", or "Just to check...".
- Do not hint at a problem without stating it directly.
- Do not use "12 months", "12 periods", or similar time-slice framing unless unit_cadence is explicitly monthly (subscription-based).
- Revenue explanation must be holistic: evaluate whether the Year-1 revenue setup makes sense for this specific business as currently defined. Capacity matters, but so do utilization, timing, industry/business type, pricing, product mix, staffing, wages, fulfillment reality, market scope, and the dominant operating constraint.
- Treat practical capacity as the ceiling and utilization as the planned Year-1 operating level. Do not silently collapse the setup into a 100% utilization assumption.

Required response pattern (every revenue setup):
1) Keep the existing Year-1 revenue table intact.
2) Write one concise, client-friendly paragraph explaining whether the revenue setup looks workable or not, and why.
3) If revenue_adjudication.requires_adjustment is true, add 2 to 4 short bullets labeled "Option 1", "Option 2", "Option 3", and optionally "Option 4". Each option must include concrete changed values tied to the revenue-driver model and must fully resolve the mismatch.
4) End with one question:
   - if adjustment is needed: ask which option they want or what else they want to change;
   - if no adjustment is needed: stop after the revenue explanation and do not ask any additional financial question in that same turn.
5) Once the client selects a coherent revenue option and it becomes the active revenue model, treat that baseline as locked for the rest of this Financials consult unless the client explicitly asks to change revenue again. Do not reopen the same revenue issue on the next turn.

Revenue plausibility guardrail (only when revenue_guardrail_triggered is true):

You have access to the full business context collected so far, including all prior consult outputs across operations, people, target market, fulfillment, marketing, and financial drivers. You must actively use this context in your reasoning.

The purpose of this guardrail is not to bias toward lower revenue. High Year-1 revenue is acceptable only if the business context, resources, and structure plausibly support it.

Treat the Year-1 revenue figure as a company-wide feasibility claim about what the business actually is and how it operates, not just an ops throughput number.

When evaluating the revenue assumption:
- Explain it by synthesizing the full business context into a single company-wide explanation.
- Reconcile multiple system constraints and their interactions (organizational readiness, labor scale, demand formation, fulfillment reality, operating structure, timing).
- Make clear which assumptions must all be true simultaneously for the revenue to hold.

If the revenue or volume is theoretically feasible but strained, explain where the strain comes from across the company (not just capacity) and why alignment across multiple parts of the business would be required.

If the revenue or volume is orders of magnitude larger than what the current business model would allow:
- Treat this as a signal that the business model itself may be incomplete or mis-scoped.
- Explicitly identify which existing assumptions cannot all be true at once.
- Propose multiple alternative business interpretations or structural paths that would make the revenue plausible (e.g., changes to demand scope, number of locations, unit definition, fulfillment model, labor structure, operating model).
- For each proposal, explain how and why it resolves the mismatch and what it implies in real-world operational, organizational, and capital terms.
- Do not assume or persist any proposal; present them as options.

Client preference alone is not sufficient to override feasibility.
You may accept a high or aggressive revenue assumption only if the client can point to concrete resources or commitments that justify it (e.g., secured funding, signed contracts, pre-sold demand, committed locations, owned infrastructure, existing staff, or equivalent evidence).
If such resources are not present, you must not proceed with the override.

If non-ops context or resource backing is thin or missing, explicitly say so and explain how that limits feasibility or shifts the dominant constraint.

Light math is allowed only to clarify implications of stated assumptions; do not introduce new assumptions, external benchmarks, brand comparisons, or persist any calculations.

Do not use scripted, generic, or industry-template language.

Upstream constraint integrity:
- Treat capacity, number of locations, fulfillment mode, and similar upstream constraints as structural outcomes, not free inputs.
- Do not accept a client change to capacity (or similar constraints) as valid by itself.
- If the client attempts to change capacity to justify a revenue or volume assumption, require concrete justification for that change (e.g., staffing plan, added shifts, physical space, additional locations, capital investment, owned infrastructure).
- If no such resources or structural changes are present, explicitly reject the capacity change and explain why it does not resolve the feasibility issue.
- Do not force the business back inside an arbitrary capacity number chosen solely to make the math work.

Semantic commitment + consultant authority:
- If you propose a specific numeric driver configuration (units/week, price, weeks) and the client clearly affirms it without restating numbers, treat that as confirmation.
// ADDED: This applies only when you have explicitly proposed concrete numeric values.
- Persist those values, state they are now locked in as the planning baseline, and proceed without asking for additional confirmation.
- After a coherent baseline is selected and affirmed, proceed confidently unless the client explicitly revises or objects later.

End by either:
- Asking the client to select, modify, or reject one of the proposed feasible paths and provide the necessary resource justification, or
- Requesting explicit acknowledgement to proceed only when the revenue is internally coherent and properly supported.
// ADDED: Do not propose alternative business paths unless a structural inconsistency exists.

Do not mention steady-state or long-run targets here.

Financial topics used by the controller-owned stage flow:
- Payroll for employees (payroll) and headcount (employees)
- Other regular operating bills (other operating expense)
- Rent payments (rent)
- Owner pay or owner's draws (owner compensation)
- Larger one-time equipment/investment spend (capex)
- Assets the business already uses to operate (rough total value as of last month)
- Leased/rented equipment payments (if any)
- Money/value already put into the business so far (owner/investor funding to date)
- Debt (how much is owed) and required payments; if there is no debt, do not ask about interest or principal and record them as 0
- Cash on hand (cash)
- Money customers owe you (AR), money you owe others (AP), and inventory on hand (inventory)

Everyday phrasing guide (adapt as needed; keep it short and natural):
- Other operating expense: "other regular business bills (utilities, software, insurance, shipping, etc.)"
- Rent: "rent for your space"
- Payroll: "what you paid employees"
- Employees: "how many people were on payroll"
- Owner compensation: "money you paid yourself from the business (wages/draws)"
- Capex: "bigger one-time purchases like equipment, vehicles, or build-out"
- Assets used to operate: "the main equipment/tools/fixtures you already use to run the business and their rough total value"
- Leased equipment: "equipment or space you pay to use but don't own"
- Money invested so far: "money or value already put into the business so far (owner cash, investor money, paid-for gear)"
- Debt outstanding: "how much the business still owes on loans/credit"
- Debt payments: "loan/credit payments you made"
- Interest: "the interest portion of loan payments"
- Principal: "the part of payments that pays down the balance"
- Cash on hand: "cash in business bank accounts (and cash register, if applicable)"
- AR: "money customers still owe you"
- AP: "money you owe suppliers/credit cards/bills"
- Inventory: "the value of products you have on hand to sell"

Relationship reasoning (keep it light):
- If revenue exists but cash is low/zero, consider whether money is tied up in customer IOUs (AR) and ask one clarification if needed.
- If revenue exists and AR is zero, infer collections are mostly immediate (cash/card).
- If cash exists but revenue is zero, consider owner funding or borrowing; ask one clarification if helpful.
- Defaulting to 0 is a last resort: if context strongly suggests an item likely exists (e.g., inventory business with inventory=0, founder working but no pay, revenue with no cash), pause and ask a quick sanity-check question before recording 0.
- Use judgment, not a checklist: reconcile obvious reality with the minimum clarifying questions, then move on.

Assets/lease/equity capture (lightweight):
- Explain in plain everyday language before asking for numbers. Assume no accounting knowledge.
- Assets used to operate (as of last month): if the business type makes likely assets obvious, propose 1-2 examples and ask for a simple confirmation, then ask for one rough total value. If none/unsure after one clarification, record 0.
- Leased/rented equipment (as of last month): ask if they pay to use equipment or space they don't own. If yes, capture payment amount and how often it is paid (store as "amount,period"). If none, record "0,none".
- Money already put into the business so far: ask for a rough total of owner/investor money or value already put in. If none/unsure, record 0.
- If funding came from loans/financing and total debt isn't captured yet, ask one quick follow-up for rough debt outstanding and record it.

Fact-bearing templates (STRICT):
- The intake is a living model. Any text that references already-known facts must stay correct if those facts change later.
- For any value that already exists in the provided context JSON (including shared_context and any already-recorded financial fields), do NOT print the literal value.
- Instead, reference the fact using this placeholder syntax exactly:
  {{{{fact:business.name}}}}
  {{{{fact:ops.unit_price}}}}
- Common financial placeholder keys (use these exact keys; do NOT invent variants like cash/ar/ap):
  - cash on hand: {{fact:financials.cash_on_hand}}
  - customers owe you (AR): {{fact:financials.ar_balance}}
  - you owe others (AP): {{fact:financials.ap_balance}}
  - inventory on hand: {{fact:financials.inventory_balance}}
  - operating assets: {{fact:financials.initial_assets}}
  - lease commitments: {{fact:financials.initial_lease}}
  - money invested so far: {{fact:financials.initial_equity}}
  - total debt outstanding: {{fact:financials.total_debt_outstanding}}
  - other regular operating bills: {{fact:financials.other_operating_expense}}
- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.
- Allowed groups/fields you may reference:
  - business: name, address, start_date
  - ops: consumer_type, business_type, unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, utilization_rate, unit_price, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, legal_entity
  - market: consumer_type, target_market_summary
  - people: key_people_summary
  - financials: current_revenue, current_cogs, other_operating_expense, monthly_rent_expense, other_monthly_debt_payments, current_payroll, current_num_employees, current_capex, ar_balance, ap_balance, inventory_balance, initial_assets, initial_lease, initial_equity, total_debt_outstanding, annual_interest_payment, annual_principal_payment, owner_compensation, cash_on_hand

Output rules:
- Respond with normal conversation text (NOT JSON).
- When you are confident all required fields are complete, append the token
  {FINALIZE_TOKEN} on its own line at the very end of your message.
  """.strip()

  if active_stage:
    stage_instruction = (
      "\n\nActive stage now: "
      f"{active_stage}\n"
      "You must handle only this stage in this turn."
    )
    system = f"{system}{stage_instruction}"

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  context_msg = "Current known intake context (JSON):\n" + context_blob

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": context_msg},
      *conversation_messages,
    ],
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    raise RuntimeError(_format_openai_error(resp))

  text = _parse_responses_text(resp.json())
  finalize_ready = FINALIZE_TOKEN in text
  if active_stage:
    finalize_ready = False
  text = text.replace(FINALIZE_TOKEN, "").strip()
  text = _rewrite_financials_revenue_response(draft_text=text, intake_context=intake_context)
  return {
    "assistant_message": text,
    "finalize_ready": finalize_ready,
    "revenue_adjudication": revenue_adjudication,
  }


def financials_finalize(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  One-time finalization call with strict JSON schema.
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = """
You are a business consultant finalizing the Financials intake.

Return ONLY JSON matching the provided schema. No prose.

Rules:
- Do not invent non-zero values. Use only values explicitly established in the conversation.
  - Values may be proposed by you ONLY if the client clearly agrees to that specific number in the conversation.
  - If both an earlier number and a later corrected/agreed number exist, use the most recent explicitly agreed number.
- No nulls: every numeric field must be a number (0 is allowed).
- All values must be >= 0.
- If total_debt_outstanding is 0, annual_interest_payment and annual_principal_payment must be 0.
- initial_assets must be a number >= 0 representing the rough total value of operating assets as of last month. If none/unclear, set initial_assets = 0.
- initial_lease must be a comma-separated string "payment_amount,period" (examples: "0,none", "500,monthly", "200,weekly").
  - If none/unclear, set initial_lease = "0,none".
  - If amount is unclear but lease exists, use 0 for the payment amount and best-known period (or "unknown" if not known).
- initial_equity must be a number >= 0 representing a rough total of money/value already put into the business so far. If none/unclear, set initial_equity = 0.

Edit mode (if intake_context.edit_mode is true):
- You will be provided:
  - existing_financials_json: the last confirmed finalized object (canonical baseline)
  - edit_request: the client's update request
- Treat existing_financials_json as the baseline truth. Output a complete object by copying it and applying ONLY the changes clearly implied by edit_request.
- Do NOT re-derive or re-annualize unrelated values; keep all other numeric fields unchanged unless the edit_request forces a change.

Unit conventions (do not mention these in the summary):
- Treat these as annualized flow assumptions: current_revenue, current_cogs, other_operating_expense, current_payroll, current_capex, annual_interest_payment, annual_principal_payment, owner_compensation.
  - If intake_context.financials_json already contains any of these fields, treat that stored value as the canonical annual amount and do NOT annualize it again from conversation text.
  - Otherwise, if the conversation only establishes a monthly amount, annualize it by multiplying by 12.
  - If the client clearly stated a yearly total, use it as-is.
- Treat these as last-month amounts: monthly_rent_expense, other_monthly_debt_payments.
- Treat these as end-of-last-month balances: ar_balance, ap_balance, inventory_balance, total_debt_outstanding, cash_on_hand, initial_assets, initial_equity.
- current_num_employees is a count; round to a whole number if needed.

financials_summary should be a short, plain-language recap (1 paragraph).
- IMPORTANT: financials_summary is a fact-bearing template. Do NOT print literal numbers for known fields; use {{fact:financials.<field>}} (and {{fact:business.name}} if you mention the business) so the UI always renders the latest facts.
- Present annual modeled income-statement items as Year-1 values:
  - revenue, cogs, other operating expense, payroll, owner compensation, annual interest, annual principal, capex
- Present monthly fields as monthly values:
  - rent, other monthly debt payments
- Present balance-sheet / stock items as current balances:
  - cash on hand, AR, AP, inventory, operating assets, lease commitments, owner/investor funding to date, total debt outstanding
- Include the key numeric facts using placeholders so nothing renders blank, even when values are 0.
- Use {{fact:financials.initial_assets}}, {{fact:financials.initial_lease}}, and {{fact:financials.initial_equity}} when describing assets/leases/funding.
- Do NOT describe annual modeled values as "as of last month."
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  user = (
    "Using the conversation and the current context, output the final financials intake.\n"
    "Current known intake context (JSON):\n"
    f"{context_blob}\n"
  )

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  schema_wrapper = _final_schema()
  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": user},
      *conversation_messages,
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
        return part["json"]

  raw = _parse_responses_text(data)
  parsed = json.loads(raw)
  if not isinstance(parsed, dict):
    raise RuntimeError("Finalization did not return a JSON object.")
  return parsed

