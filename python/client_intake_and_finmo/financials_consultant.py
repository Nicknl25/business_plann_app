from __future__ import annotations

import json
import os
import re
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
- Treat business_stage as a global realism modifier, not a cosmetic label:
  - pre-revenue: emphasize launch readiness, proving first demand, and early traction realism; do not assume established channel efficiency or repeat demand unless the facts explicitly show it.
  - early-stage: emphasize ramp, acquisition realism, and early operational strain; do not assume mature repeatability unless the facts support it.
  - operating: assume some installed base, historical channel knowledge, and repeat demand patterns unless the facts contradict that; weigh optimization, retention, and scaling efficiency more heavily than startup-style discovery framing.
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
            "set_percent",
            "set_adjustment",
            "ask_question",
            "unclear",
          ],
        },
        "cogs_total_year1": {"type": ["number", "null"]},
        "cogs_percent_of_revenue": {"type": ["number", "null"]},
        "cogs_adjustment": {"type": ["number", "null"]},
        "question_or_clarification": {"type": "string"},
      },
      "required": [
        "intent_type",
        "cogs_total_year1",
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
          "You are interpreting a client's reply to a Year-1 COGS baseline proposal in an intake consult.\n"
          "Classify whether the client accepts the baseline, sets a new total annual COGS amount, gives a COGS percent of revenue, gives an additive adjustment from baseline, asks a question, or is unclear.\n"
          "Do not rely on exact keywords. Use the assistant proposal, the numeric baseline context, and the user's reply together.\n"
          "If the user asks a question or is unclear, put the follow-up text in question_or_clarification.\n"
          "For set_percent, return the percent as a decimal fraction when clear (for example 0.42 for 42%)."
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


def _cogs_estimate_schema() -> Dict[str, Any]:
  return {
    "name": "financials_cogs_estimate",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "estimated_cogs_percent": {"type": "number"},
        "brief_rationale": {"type": "string"},
      },
      "required": ["estimated_cogs_percent", "brief_rationale"],
    },
  }


def estimate_cogs_percent_from_context(
  *,
  cogs_estimate_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  if not isinstance(cogs_estimate_context, dict):
    return None
  naics_6 = str(cogs_estimate_context.get("business_naics_6") or "").strip()
  financials_year1_json = dict(cogs_estimate_context.get("financials_year1_json") or {})
  revenue_year1 = float(financials_year1_json.get("company_revenue_total_year1") or 0.0)
  if revenue_year1 <= 0 or not naics_6:
    return None

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _cogs_estimate_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are producing a single Year-1 direct-cost estimate for a business-plan intake when exact industry COGS benchmark coverage is unavailable.\n"
          "Return one best estimated COGS percent of revenue as a decimal fraction, not a range.\n"
          "COGS here means direct fulfillment/delivery costs only. Do not include payroll, rent, owner pay, marketing, or general overhead unless the business model clearly makes them direct fulfillment costs.\n"
          "Use the exact 6-digit NAICS, business type, operating model, pricing, capacity, cadence, staffing context, and all other provided business facts.\n"
          "Do not use broad parent-NAICS averages. Do not ask questions. You must return one usable estimate."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(cogs_estimate_context, ensure_ascii=False),
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
  for _ in range(2):
    try:
      resp = _post_openai(url=url, headers=headers, payload=payload)
    except Exception:
      continue
    if resp.status_code >= 400:
      continue
    try:
      parsed = _parse_responses_json(resp.json())
    except Exception:
      continue
    if not isinstance(parsed, dict):
      continue
    try:
      percent = float(parsed.get("estimated_cogs_percent"))
    except Exception:
      continue
    percent = max(0.0, min(percent, 1.0))
    return {
      "estimated_cogs_percent": percent,
      "brief_rationale": str(parsed.get("brief_rationale") or "").strip(),
    }
  return None


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


def _marketing_estimate_schema() -> Dict[str, Any]:
  return {
    "name": "financials_marketing_estimate",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "reachable_market": {"type": "number"},
        "reachable_market_b2c": {"type": "number"},
        "reachable_market_b2b": {"type": "number"},
        "capture_rate_year1": {"type": "number"},
        "expected_customers_or_clients_year1": {"type": "number"},
        "expected_units_year1": {"type": "number"},
        "marketing_intensity": {
          "type": "string",
          "enum": ["low", "medium", "high", "very_high"],
        },
        "baseline_marketing_percent": {"type": "number"},
        "brief_rationale": {"type": "string"},
      },
      "required": [
        "reachable_market",
        "reachable_market_b2c",
        "reachable_market_b2b",
        "capture_rate_year1",
        "expected_customers_or_clients_year1",
        "expected_units_year1",
        "marketing_intensity",
        "baseline_marketing_percent",
        "brief_rationale",
      ],
    },
  }


def _marketing_estimate_review_schema() -> Dict[str, Any]:
  return {
    "name": "financials_marketing_estimate_review",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "proceed": {"type": "boolean"},
        "feedback": {"type": "string"},
      },
      "required": ["proceed", "feedback"],
    },
  }


def _validate_marketing_estimate_candidate(
  *,
  marketing_estimate_context: Dict[str, Any],
  estimate_candidate: Dict[str, Any],
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _marketing_estimate_review_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are validating an internal Year-1 marketing estimate candidate.\n"
          "Approve only if the candidate is coherent with the observed market basis and the business context.\n"
          "Rules:\n"
          "- B2B reach must stay grounded in the observed CBP firm universe.\n"
          "- B2B reach may narrow from CBP, but should not drift away from that base.\n"
          "- B2B reachable market should represent only the realistic Year-1 subset of the CBP establishment universe that can actually be reached given the sales model, channels, onboarding/sales friction, geography, and Year-1 business-development realism in the provided context.\n"
          "- Do not treat most of the CBP universe as reachable by default.\n"
          "- Avoid candidates where reachable_market_b2b sits close to the full CBP establishment universe unless the rationale explicitly justifies why that unusually broad reach is realistic in Year 1.\n"
          "- B2B reach should not collapse to an unrealistically tiny share of the observed CBP universe unless the rationale clearly justifies why.\n"
          "- B2C reach may be GPT-compressed from ACS basis counts because no exact behavioral/intersection data exists.\n"
          "- But B2C must still narrow to the actual user type implied by the business model rather than treating broad ACS population ceilings as the reachable market.\n"
          "- In mixed cases, B2C and B2B are different measurement types and must stay conceptually separate.\n"
          "- In mixed cases, avoid neat or symmetrical component splits unless the observed data actually supports them.\n"
          "- Combined reachable_market is a planning/reporting abstraction, not a literal additive homogeneous TAM count.\n"
          "- reachable_market, reachable_market_b2c, and reachable_market_b2b are entity-level counts (people/customers for B2C; firms/accounts for B2B).\n"
          "- expected_units_year1 is a unit-level output and may reflect repeat or recurring units per reachable entity.\n"
          "- capture_rate_year1 must be interpreted as units relative to reachable entities, not as a simple one-time adoption percentage.\n"
          "- Do not imply that capture_rate_year1 equals the percent of the total market adopting the product.\n"
          "- If capture_rate_year1 looks high, the rationale must explain it using the actual unit mechanics already implied by the business model, such as recurring periods, repeat purchases, multiple units per entity, or account/user structure.\n"
          "- Treat business_stage as a global realism modifier:\n"
          "  - pre-revenue: keep the rationale centered on launch readiness, early awareness, testing, and first traction; do not assume mature installed-base behavior unless the facts explicitly support it.\n"
          "  - early-stage: keep the rationale centered on ramp, acquisition, proving repeatability, and early operational strain.\n"
          "  - operating: assume some existing customer base, historical channel knowledge, and prior traction unless the facts contradict that; focus more on optimization, retention, repeat demand, and scaling efficiency than on discovery framing.\n"
          "- If the candidate is acceptable, return proceed=true and feedback as an empty string.\n"
          "- If not acceptable, return proceed=false and feedback as one short internal correction note."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "marketing_estimate_context": marketing_estimate_context,
            "estimate_candidate": estimate_candidate,
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
    return {"proceed": True, "feedback": ""}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {"proceed": True, "feedback": ""}
  return parsed if isinstance(parsed, dict) else {"proceed": True, "feedback": ""}


def estimate_marketing_baseline_from_context(
  *,
  marketing_estimate_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  if not isinstance(marketing_estimate_context, dict):
    return None
  revenue_year1 = float(
    ((marketing_estimate_context.get("financials_year1_json") or {}).get("company_revenue_total_year1") or 0.0)
  )
  if revenue_year1 <= 0:
    return None

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _marketing_estimate_schema()
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  retry_feedback = ""
  for _ in range(3):
    request_context = dict(marketing_estimate_context or {})
    if retry_feedback:
      request_context["estimate_feedback"] = retry_feedback
    payload = {
      "model": model,
      "input": [
        {
          "role": "system",
          "content": (
            "You are producing a Year-1 marketing baseline for a business-plan intake.\n"
            "Your job is to translate observed market-basis signals into one realistic Year-1 marketing percent of revenue.\n"
            "Important rules:\n"
            "- Treat B2C and B2B basis signals as observed inputs, not exact intersections.\n"
            "- Do not multiply separate basis signals together into fake precise target-market counts.\n"
            "- Use the observed signals, normalized geography, offer, pricing, sales model, and Year-1 revenue/unit requirements together.\n"
            "- reachable_market is the combined reachable market across all applicable basis types.\n"
            "- reachable_market_b2c is the population-based reachable component only.\n"
            "- reachable_market_b2b is the firm-based reachable component only.\n"
            "- If only one basis type applies, set the other component to 0.\n"
            "- If both basis types apply, keep the components informational and make reachable_market a coherent combined figure.\n"
            "- reachable_market is a planning/reporting field only. Do not present it as one literal homogeneous TAM count when both B2C and B2B are present.\n"
            "- In mixed cases, keep B2C people reach and B2B firm reach conceptually separate in your reasoning and in brief_rationale.\n"
            "- Do not produce neat or symmetrical B2C/B2B splits unless the observed data clearly supports that symmetry.\n"
            "- B2B reach must stay anchored to the observed CBP firm universe provided in context.\n"
            "- reachable_market_b2b is a reachable subset of the observed CBP firm universe, not a free-floating estimate.\n"
            "- Regional and national B2B reach must stay grounded in the observed state-level CBP firm universe.\n"
            "- reachable_market_b2b must never exceed the observed B2B firm universe provided in context.\n"
            "- reachable_market_b2b should reflect only the realistic Year-1 reachable subset of that CBP universe given the sales model, channels, onboarding/sales friction, geography, and Year-1 business-development realism already in the context.\n"
            "- Do not treat most of the CBP universe as reachable by default.\n"
            "- Avoid selecting values close to the full CBP establishment universe unless the rationale explicitly justifies why that unusually broad reach is realistic in Year 1.\n"
            "- reachable_market_b2b should not collapse to an unrealistically tiny fraction of the observed CBP universe unless the rationale clearly justifies why.\n"
            "- B2C reach must be anchored to the actual user type implied by the business model, offer, and target-market description; do not treat the full ACS audience ceiling as the reachable market.\n"
            "- For B2C, ACS basis counts are an observed ceiling only. They are not the answer.\n"
            "- For B2C, explicitly narrow from broad population -> relevant user group -> reachable subset.\n"
            "- Avoid using large local, regional, or national population counts directly as reachable_market_b2c when the actual user type is a narrower role-based or behavior-based audience.\n"
            "- Apply that B2C narrowing discipline across all scopes: local, regional, and national.\n"
            "- geography_basis is the hard scope anchor. Respect it.\n"
            "- If scope is local, reachable_market must reflect only the local footprint implied by the anchor ZIP, county basis, and coverage summary. Do not treat a state-level observed universe as directly reachable.\n"
            "- If scope is regional, reachable_market must be constrained to the provided regional state/county basis, not the entire country.\n"
            "- If scope is national, reason from national reachability rather than ZIP/county footprint.\n"
            "- Treat ZIP/county/state basis as backend aggregation anchors. Do not assume the client explicitly named every ZIP unless it appears in explicit_zip_basis.\n"
            "- Marketing here means the spend required to support the Year-1 demand assumption. It does not set revenue by itself.\n"
            "- Ops/capacity remains the ceiling.\n"
            "- Return one point estimate, not a range.\n"
            "- baseline_marketing_percent must be a decimal fraction of revenue between 0 and 1.\n"
            "- reachable_market, capture_rate_year1, expected_customers_or_clients_year1, and expected_units_year1 must be internally coherent with the provided context.\n"
            "- reachable_market, reachable_market_b2c, and reachable_market_b2b are entity-level counts, while expected_units_year1 is a unit-level output.\n"
            "- capture_rate_year1 must be interpreted as units relative to reachable entities, not as a simple one-time adoption rate.\n"
            "- Do not imply that capture_rate_year1 equals the percent of the total market adopting the product.\n"
            "- If capture_rate_year1 appears high, explain it using the actual unit mechanics implied by the business model and unit definition (for example, recurring periods, repeat purchases, multiple units per entity, or account/user structure).\n"
            "- brief_rationale must separate the B2C people-based reach from the B2B firm-based reach whenever both are present, and must describe reachable_market as a planning/reporting view rather than one literal combined TAM.\n"
            "- For B2C, brief_rationale must explicitly explain the narrowing from broad ACS population basis to the actual user type and then to the reachable subset.\n"
            "- Treat business_stage as a global reasoning constraint:\n"
            "  - pre-revenue: frame the estimate around launch readiness, awareness, testing, and first traction; do not write as if the business already has stable repeat demand or mature channel optimization.\n"
            "  - early-stage: frame the estimate around ramp, acquisition, proving repeatability, and early operational strain.\n"
            "  - operating: assume some existing customer base, historical channel knowledge, and prior traction unless the facts contradict that; focus more on optimization, retention, repeatability, and scaling efficiency than on startup-style discovery.\n"
            "- Avoid false precision in brief_rationale; explain the grounding honestly.\n"
            "- If estimate_feedback is present in the context, correct the estimate accordingly.\n"
            "- Do not ask questions."
          ),
        },
        {
          "role": "user",
          "content": json.dumps(request_context, ensure_ascii=False),
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
    try:
      resp = _post_openai(url=url, headers=headers, payload=payload)
    except Exception:
      continue
    if resp.status_code >= 400:
      continue
    try:
      parsed = _parse_responses_json(resp.json())
    except Exception:
      continue
    if not isinstance(parsed, dict):
      continue
    try:
      baseline_percent = float(parsed.get("baseline_marketing_percent"))
      reachable_market = float(parsed.get("reachable_market"))
      reachable_market_b2c = float(parsed.get("reachable_market_b2c"))
      reachable_market_b2b = float(parsed.get("reachable_market_b2b"))
      capture_rate = float(parsed.get("capture_rate_year1"))
      expected_customers = float(parsed.get("expected_customers_or_clients_year1"))
      expected_units = float(parsed.get("expected_units_year1"))
    except Exception:
      continue
    try:
      b2b_universe = float(
        ((marketing_estimate_context.get("market_measurement_guidance") or {}).get("b2b_observed_establishments_total")) or 0.0
      )
    except Exception:
      b2b_universe = 0.0
    baseline_percent = max(0.0, min(baseline_percent, 1.0))
    capture_rate = max(0.0, min(capture_rate, 1.0))
    if b2b_universe > 0:
      reachable_market_b2b = min(max(0.0, reachable_market_b2b), b2b_universe)
    else:
      reachable_market_b2b = max(0.0, reachable_market_b2b)
    reachable_market_b2c = max(0.0, reachable_market_b2c)
    reachable_market = max(0.0, reachable_market, reachable_market_b2c, reachable_market_b2b)
    estimate_candidate = {
      "reachable_market": reachable_market,
      "reachable_market_b2c": reachable_market_b2c,
      "reachable_market_b2b": reachable_market_b2b,
      "capture_rate_year1": capture_rate,
      "expected_customers_or_clients_year1": max(0.0, expected_customers),
      "expected_units_year1": max(0.0, expected_units),
      "marketing_intensity": str(parsed.get("marketing_intensity") or "").strip() or "medium",
      "baseline_marketing_percent": baseline_percent,
      "brief_rationale": str(parsed.get("brief_rationale") or "").strip(),
    }
    review = _validate_marketing_estimate_candidate(
      marketing_estimate_context=request_context,
      estimate_candidate=estimate_candidate,
    )
    if bool(review.get("proceed")):
      return estimate_candidate
    retry_feedback = str(review.get("feedback") or "").strip() or (
      "Tighten the estimate so B2B stays grounded in CBP, B2C remains a separate compressed consumer reach, "
      "and combined reachable_market stays a planning abstraction."
    )
  return None


def _marketing_reply_schema() -> Dict[str, Any]:
  return {
    "name": "financials_marketing_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": [
            "accept_baseline",
            "set_total",
            "set_percent",
            "set_adjustment",
            "ask_question",
            "unclear",
          ],
        },
        "marketing_total_year1": {"type": ["number", "null"]},
        "marketing_percent_of_revenue": {"type": ["number", "null"]},
        "marketing_adjustment": {"type": ["number", "null"]},
        "question_or_clarification": {"type": "string"},
      },
      "required": [
        "intent_type",
        "marketing_total_year1",
        "marketing_percent_of_revenue",
        "marketing_adjustment",
        "question_or_clarification",
      ],
    },
  }


def interpret_marketing_reply(
  *,
  user_message: str,
  last_assistant: str,
  marketing_context: Dict[str, Any],
) -> Dict[str, Any]:
  if not str(user_message or "").strip():
    return {}

  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _marketing_reply_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply to a Year-1 marketing baseline proposal.\n"
          "Classify whether the client accepts the baseline, sets a new total annual marketing amount, gives a marketing percent of revenue, gives an additive adjustment from baseline, asks a question, or is unclear.\n"
          "Do not rely on exact keywords. Use the assistant proposal, the numeric baseline context, and the user's reply together.\n"
          "For set_percent, return the percent as a decimal fraction.\n"
          "If the user asks a question or is unclear, put the follow-up text in question_or_clarification."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": str(last_assistant or "").strip(),
            "marketing_context": marketing_context,
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


def _marketing_validation_schema() -> Dict[str, Any]:
  return {
    "name": "financials_marketing_validation",
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


def validate_marketing_setup(
  *,
  intake_context: Dict[str, Any],
  marketing_context: Dict[str, Any],
  user_message: str,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _marketing_validation_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are validating a proposed Year-1 marketing setup for an intake consult.\n"
          "The baseline came from the observed market basis and the business context, and the client may have accepted it or adjusted it.\n"
          "Decide whether the resulting Year-1 marketing setup is coherent enough to proceed.\n"
          "Use the market basis, demand expectations, business model, pricing, geography, and final marketing total/percent.\n"
          "Treat any B2B reach assumptions as subsets of the observed CBP firm universe, not as free-floating counts.\n"
          "Treat B2B reachable market as the realistic Year-1 subset of the CBP universe that can actually be reached given the sales model, channels, onboarding/sales friction, geography, and Year-1 business-development realism already in context.\n"
          "Do not allow the model to treat most of the CBP universe as reachable by default unless the context clearly justifies that unusually broad reach.\n"
          "Do not allow B2B reach to collapse to an implausibly tiny share of the observed CBP universe without clear justification from the context.\n"
          "Treat any B2C reach assumptions as narrowed reachable subsets of the broad ACS audience ceiling, anchored to the actual user type implied by the business model.\n"
          "Do not allow broad ACS population ceilings to be treated as the reachable B2C market directly.\n"
          "In mixed B2C/B2B cases, keep B2C people reach and B2B firm reach conceptually separate; combined reachable market is a planning abstraction only.\n"
          "Treat reachable-market fields as entity counts and expected_units_year1 as unit output; capture rate should be interpreted as units relative to reachable entities, not pure adoption rate.\n"
          "If capture looks high, it must be explainable by the actual unit mechanics already implied by the business model rather than by vague market-adoption language.\n"
          "Treat business_stage as a global realism modifier:\n"
          "- pre-revenue: keep the setup and acknowledgement framed around launch readiness, early awareness, testing, and first traction rather than mature optimization.\n"
          "- early-stage: keep the setup and acknowledgement framed around ramp, acquisition, and proving repeatability.\n"
          "- operating: assume some existing customer base, historical channel knowledge, and prior traction unless the facts contradict that; focus more on optimization, retention, repeatability, and scaling efficiency than on discovery framing.\n"
          "If it is coherent enough for intake, set proceed=true and return a very short acknowledgement or an empty string.\n"
          "If it is structurally inconsistent, set proceed=false and ask one short clarification question.\n"
          "Do not ask the client to calculate the market from scratch.\n"
          "Do not rely on exact keywords."
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "intake_context": intake_context,
            "marketing_context": marketing_context,
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


def _monthly_rent_reply_schema() -> Dict[str, Any]:
  return {
    "name": "financials_monthly_rent_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": ["set_none", "set_value", "ask_question", "unclear"],
        },
        "monthly_rent_expense": {"type": ["number", "null"]},
        "question_or_clarification": {"type": "string"},
      },
      "required": ["intent_type", "monthly_rent_expense", "question_or_clarification"],
    },
  }


def interpret_monthly_rent_reply(
  *,
  user_message: str,
  last_assistant: str,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _monthly_rent_reply_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply to a business-space rent question.\n"
          "This field is only monthly rent for dedicated business space such as an office, storefront, clinic, studio, kitchen, or warehouse.\n"
          "Interpret human meaning, not keywords.\n"
          "If the client indicates they do not pay for dedicated business space, return set_none.\n"
          "If the client gives a monthly amount, return set_value with the numeric amount only.\n"
          "If the client says they work from home, are remote, do not have space yet, or do not need dedicated space, treat that as set_none.\n"
          "If the client asks a question, return ask_question.\n"
          "If the reply is too unclear to use, return unclear.\n"
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "last_assistant": str(last_assistant or "").strip(),
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
    return {"intent_type": "unclear", "monthly_rent_expense": None, "question_or_clarification": ""}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {"intent_type": "unclear", "monthly_rent_expense": None, "question_or_clarification": ""}
  return (
    parsed
    if isinstance(parsed, dict)
    else {"intent_type": "unclear", "monthly_rent_expense": None, "question_or_clarification": ""}
  )


def _future_rent_reply_schema() -> Dict[str, Any]:
  return {
    "name": "financials_future_rent_reply",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "intent_type": {
          "type": "string",
          "enum": ["set_true", "set_false", "ask_question", "unclear"],
        },
        "future_rent_expected": {"type": ["boolean", "null"]},
        "question_or_clarification": {"type": "string"},
      },
      "required": ["intent_type", "future_rent_expected", "question_or_clarification"],
    },
  }


def interpret_future_rent_reply(
  *,
  user_message: str,
  last_assistant: str,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _future_rent_reply_schema()
  payload = {
    "model": model,
    "input": [
      {
        "role": "system",
        "content": (
          "You are interpreting a client's reply about whether the business is expected to need paid dedicated space later.\n"
          "Interpret human meaning, not keywords.\n"
          "If the client indicates they do expect to need paid dedicated business space later, return set_true.\n"
          "If the client indicates they do not expect to need paid dedicated business space later, return set_false.\n"
          "If the client asks a question, return ask_question.\n"
          "If the reply is too unclear to use confidently, return unclear.\n"
        ),
      },
      {
        "role": "user",
        "content": json.dumps(
          {
            "last_assistant": str(last_assistant or "").strip(),
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
    return {"intent_type": "unclear", "future_rent_expected": None, "question_or_clarification": ""}
  try:
    parsed = _parse_responses_json(resp.json())
  except Exception:
    return {"intent_type": "unclear", "future_rent_expected": None, "question_or_clarification": ""}
  return (
    parsed
    if isinstance(parsed, dict)
    else {"intent_type": "unclear", "future_rent_expected": None, "question_or_clarification": ""}
  )


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
- Treat business_stage as a global realism/tone modifier:
  - pre-revenue: explain the setup in terms of launch readiness, first demand, and early traction realism; do not write like a mature operator unless the facts explicitly support it.
  - early-stage: explain the setup in terms of ramp, acquisition realism, and proving repeatability.
  - operating: assume some installed base, historical channel knowledge, and repeat demand unless the facts contradict that; use optimization, retention, and scaling language rather than startup-style discovery language.
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

Senior consultant lens (LIGHT plausibility checks; the final planning pass is the final arbitrator):
- Treat the outputs of Ops, People, and Market as fixed reality inputs provided in the context JSON (often under shared_context). Do not re-run intake, do not re-explain the business, and do not ask the client to reconfirm upstream facts.
- Use those upstream facts to do gentle feasibility checks and flag obvious contradictions (not precision accounting).
- When a number clearly does not fit upstream reality, ask ONE targeted clarifying question; you MAY suggest a corrected value (or tight range) as a proposal.
- If the client agrees to a correction, record it and continue.
- If the client rejects the correction or it remains unclear after minimal clarification, record the client's number as provisional and keep going; the final planning pass will arbitrate cross-domain contradictions later.

Core rule for this section:
- Do not ask the client to choose or label a time basis. Use the anchor "as of last month".
- Anchor everything to "as of last month". If the client doesn't have the item, explicitly tell them you're recording 0 and move on.
- Nothing should be left unknown: if you can't get a clear answer after minimal clarification, record 0 and move on.
- Exception: current_revenue, current_cogs, current_payroll, and marketing_total_year1 are modeled Year-1 values when already present. Treat them as established and move to the next unanswered item.

Style:
- One plain question sentence per message.
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

COGS handling:
- If current_cogs or cogs_total_year1 is already present in context, treat Year-1 direct costs as established and move on.

Payroll handling (REPLACES payroll question when already present):
- If current_payroll or payroll_total_year1 is already present in context, treat Year-1 payroll as established.
- Do not ask a monthly or historical payroll question once that Year-1 payroll value exists.

Marketing handling:
- If marketing_total_year1 or marketing_percent_of_revenue is already present in context, treat Year-1 marketing as established and move on.

Stage control:
- The controller may provide financials_active_stage in the context.
- If financials_active_stage is present, you must handle ONLY that one stage and nothing else.
- Do not skip ahead, do not bundle later financial topics, and do not ask about a different stage.
- If financials_active_stage is "revenue_intro" and revenue does not need adjustment, explain the revenue setup only and stop; the controller will advance to the next stage.
- For other stages, ask exactly one question for that stage only.

Stage names:
- revenue_intro
- cogs
- current_payroll
- marketing
- monthly_rent_expense
- future_rent_expected
- owner_compensation
- other_operating_expense
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
// ADDED: Do not propose alternative business paths unless a structural conflict exists.

Do not mention steady-state or long-run targets here.

Financial topics used by the stage flow:
- Payroll for employees (payroll) and headcount (employees)
- Year-1 marketing budget (marketing)
- Other regular operating bills excluding payroll, marketing, and rent (other operating expense)
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
- Marketing: "your Year-1 marketing/advertising budget"
- Other operating expense: "other regular business bills besides payroll, marketing, and rent (utilities, software, insurance, shipping, etc.)"
- Rent: "rent for your space"
- Future rent signal: "whether you expect to need paid dedicated business space later"
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
  - marketing budget: {{fact:financials.marketing_total_year1}}
  - other regular operating bills: {{fact:financials.other_operating_expense}}
- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.
- Allowed groups/fields you may reference:
  - business: name, address, start_date
  - ops: consumer_type, business_type, unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, utilization_rate, unit_price, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, legal_entity
  - market: consumer_type, target_market_summary
  - people: key_people_summary
  - financials: current_revenue, current_cogs, marketing_total_year1, marketing_percent_of_revenue, other_operating_expense, monthly_rent_expense, other_monthly_debt_payments, current_payroll, current_num_employees, current_capex, ar_balance, ap_balance, inventory_balance, initial_assets, initial_lease, initial_equity, total_debt_outstanding, annual_interest_payment, annual_principal_payment, owner_compensation, cash_on_hand

Output rules:
- Respond with normal conversation text (NOT JSON).
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
  finalize_ready = False
  text = _rewrite_financials_revenue_response(draft_text=text, intake_context=intake_context)
  return {
    "assistant_message": text,
    "finalize_ready": finalize_ready,
    "revenue_adjudication": revenue_adjudication,
  }


