from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _extract_output_json(data: Dict[str, Any]) -> Dict[str, Any]:
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
  # Fallback: some responses may return output_text even with schema.
  text_chunks: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        text_chunks.append(str(part["text"]))
  raw = "\n".join(text_chunks).strip()
  parsed = json.loads(raw) if raw else {}
  if not isinstance(parsed, dict):
    raise RuntimeError("Model card proposer did not return a JSON object.")
  return parsed


def propose_marketing_suggestions(
  *,
  business_name: str,
  business_type: str,
  naics_6: Optional[str],
  today_iso: str,
  business_start_date: Optional[str],
  consumer_type: str,
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  lobs: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
  """
  GPT-backed proposer for Marketing model cards.

  Returns a list of suggestion dicts, each with:
    {lob_key, lob_name?, monthly_marketing_budget, year1_marketing_spend, primary_channels, basis}
  """
  # Only propose for user-visible LOBs; company_total is system-managed.
  lob_list = []
  for lob in list(lobs or []):
    lk = str(lob.get("lob_key") or "").strip()
    if not lk or lk == "company_total":
      continue
    lob_list.append({"lob_key": lk, "lob_name": str(lob.get("lob_name") or "").strip()})
  if not lob_list:
    lob_list = [{"lob_key": "company_total", "lob_name": ""}]

  schema = {
    "name": "marketing_model_card_proposer",
    "strict": True,
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "suggestions": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lob_key": {"type": "string"},
              "lob_name": {"type": ["string", "null"]},
              "monthly_marketing_budget": {"type": "number"},
              "year1_marketing_spend": {"type": "number"},
              "primary_channels": {"type": "string"},
              "basis": {"type": "string"},
            },
            "required": [
              "lob_key",
              "monthly_marketing_budget",
              "year1_marketing_spend",
              "primary_channels",
              "basis",
            ],
          },
        }
      },
      "required": ["suggestions"],
    },
  }

  system = (
    "You propose numeric model drivers first so the client never has to invent numbers.\n"
    "You MUST infer a reasonable starting point from context (industry/NAICS, stage, timing/ramp) and propose it.\n"
    "Marketing may legitimately be $0 in Year 1 (for example: contract/offtake driven demand, regulatory/utility buyers, long sales cycles, or the founder is relying purely on relationships).\n"
    "Use judgment from NAICS + ops context (sales motion, customer type, contracts vs. demand, regulation) to decide whether marketing spend exists at all.\n"
    "If marketing spend is $0, still propose it explicitly and explain why (basis) and what would change your mind.\n"
    "The client will Accept or Edit; do not ask open-ended 'what is your budget?' questions.\n"
    "Do not use rigid formulas. Use judgment grounded in NAICS + what is already known.\n"
    "If the business start date is in the future or very recent, reflect a ramp (pre-launch, early ramp).\n"
    "Always keep proposals conservative and easy to adjust.\n"
    "Return JSON only per the schema."
  )

  user = {
    "business_name": business_name,
    "business_type": business_type,
    "naics_6": naics_6,
    "today_iso": today_iso,
    "business_start_date": business_start_date,
    "consumer_type": consumer_type,
    "lobs": lob_list,
    "ops": ops_json,
    "target_market": target_market_json,
    "shared_context": shared_context,
  }

  api_key = _require_openai_key()
  model = _openai_model()
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ],
    "response_format": {"type": "json_schema", "json_schema": schema},
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 300:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
  data = resp.json()
  parsed = _extract_output_json(data)
  suggestions = parsed.get("suggestions")
  if not isinstance(suggestions, list) or not suggestions:
    raise RuntimeError("Marketing proposer returned no suggestions.")

  cleaned: List[Dict[str, Any]] = []
  for s in suggestions:
    if not isinstance(s, dict):
      continue
    lob_key = str(s.get("lob_key") or "").strip() or "company_total"
    if lob_key == "company_total":
      # Allowed for single-LOB, but if multi-LOB exists we prefer per-LOB suggestions.
      pass

    def _req_number(field: str) -> float:
      val = s.get(field)
      if isinstance(val, (int, float)):
        return float(val)
      raw = str(val or "").strip()
      if not raw:
        raise RuntimeError(f"Marketing proposer missing required numeric field: {field}")
      try:
        return float(raw)
      except Exception as exc:
        raise RuntimeError(f"Marketing proposer invalid numeric field {field}: {raw}") from exc

    cleaned.append(
      {
        "lob_key": lob_key,
        "lob_name": str(s.get("lob_name") or "").strip() or None,
        "monthly_marketing_budget": _req_number("monthly_marketing_budget"),
        "year1_marketing_spend": _req_number("year1_marketing_spend"),
        "primary_channels": str(s.get("primary_channels") or "").strip(),
        "basis": str(s.get("basis") or "").strip(),
      }
    )
  return cleaned or []


def propose_milestones_suggestions(
  *,
  business_name: str,
  business_type: str,
  naics_6: Optional[str],
  today_iso: str,
  business_start_date: Optional[str],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  lobs: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
  """
  GPT-backed proposer for Milestones model cards.

  Returns a list of suggestion dicts, each with:
    {lob_key, lob_name?, milestones: [{title, description, target_period, confidence}]}
  """
  # Only propose for user-visible LOBs; company_total is system-managed and can hold shared milestones.
  lob_list = []
  for lob in list(lobs or []):
    lk = str(lob.get("lob_key") or "").strip()
    if not lk or lk == "company_total":
      continue
    lob_list.append({"lob_key": lk, "lob_name": str(lob.get("lob_name") or "").strip()})
  if not lob_list:
    lob_list = [{"lob_key": "company_total", "lob_name": ""}]

  schema = {
    "name": "milestones_model_card_proposer",
    "strict": True,
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "suggestions": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lob_key": {"type": "string"},
              "lob_name": {"type": ["string", "null"]},
              "milestones": {
                "type": "array",
                "minItems": 1,
                "items": {
                  "type": "object",
                  "additionalProperties": False,
                  "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "target_period": {"type": "string"},
                    "confidence": {"type": "number"},
                  },
                  "required": ["title", "description", "target_period", "confidence"],
                },
              },
            },
            "required": ["lob_key", "milestones"],
          },
        }
      },
      "required": ["suggestions"],
    },
  }

  system = (
    "You propose milestone options first so the client never has to invent milestones.\n"
    "Infer realistic milestones grounded in industry/NAICS, the business stage, and timing/ramp.\n"
    "Milestones are NOT math drivers; they are commitments/goals that increase clarity and readiness.\n"
    "Return 2–4 milestones per LOB. Each milestone must be concrete and measurable.\n"
    "target_period should be plain English (e.g., 'within 6 months of launch', 'by end of Year 1').\n"
    "confidence must be between 0.0 and 1.0.\n"
    "Return JSON only per the schema."
  )

  user = {
    "business_name": business_name,
    "business_type": business_type,
    "naics_6": naics_6,
    "today_iso": today_iso,
    "business_start_date": business_start_date,
    "lobs": lob_list,
    "ops": ops_json,
    "shared_context": shared_context,
  }

  api_key = _require_openai_key()
  model = _openai_model()
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ],
    "response_format": {"type": "json_schema", "json_schema": schema},
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 300:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
  data = resp.json()
  parsed = _extract_output_json(data)
  suggestions = parsed.get("suggestions")
  if not isinstance(suggestions, list) or not suggestions:
    raise RuntimeError("Milestones proposer returned no suggestions.")

  cleaned: List[Dict[str, Any]] = []
  for s in suggestions:
    if not isinstance(s, dict):
      continue
    lob_key = str(s.get("lob_key") or "").strip() or "company_total"
    raw_milestones = s.get("milestones")
    if not isinstance(raw_milestones, list) or not raw_milestones:
      continue
    milestones_out: List[Dict[str, Any]] = []
    for m in raw_milestones:
      if not isinstance(m, dict):
        continue
      title = str(m.get("title") or "").strip()
      description = str(m.get("description") or "").strip()
      target_period = str(m.get("target_period") or "").strip()
      try:
        conf = float(m.get("confidence"))
      except Exception:
        conf = 0.6
      if not title or not target_period:
        continue
      conf = min(1.0, max(0.0, conf))
      milestones_out.append(
        {
          "title": title,
          "description": description,
          "target_period": target_period,
          "confidence": conf,
        }
      )
    if not milestones_out:
      continue
    cleaned.append(
      {
        "lob_key": lob_key,
        "lob_name": str(s.get("lob_name") or "").strip() or None,
        "milestones": milestones_out,
      }
    )

  return cleaned or []


def propose_headcount_suggestions(
  *,
  business_name: str,
  business_type: str,
  naics_6: Optional[str],
  today_iso: str,
  business_start_date: Optional[str],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  lobs: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
  """
  GPT-backed proposer for Headcount model cards.

  Returns a list of suggestion dicts, each with:
    {
      lob_key,
      lob_name?,
      roles: [{
        role_title, employee_count, hours_per_week, weeks_per_year,
        fallback_hourly_rate, fallback_hourly_rate_basis,
        rationale
      }],
      basis
    }
  """
  # Only propose for user-visible LOBs; company_total is system-managed.
  lob_list = []
  for lob in list(lobs or []):
    lk = str(lob.get("lob_key") or "").strip()
    if not lk or lk == "company_total":
      continue
    lob_list.append({"lob_key": lk, "lob_name": str(lob.get("lob_name") or "").strip()})
  if not lob_list:
    lob_list = [{"lob_key": "company_total", "lob_name": ""}]

  schema = {
    "name": "headcount_model_card_proposer",
    "strict": True,
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "suggestions": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lob_key": {"type": "string"},
              "lob_name": {"type": ["string", "null"]},
              "basis": {"type": "string"},
              "roles": {
                "type": "array",
                "minItems": 1,
                "items": {
                  "type": "object",
                  "additionalProperties": False,
                  "properties": {
                    "role_title": {"type": "string"},
                    "employee_count": {"type": "integer"},
                    "hours_per_week": {"type": "number"},
                    "weeks_per_year": {"type": "number"},
                    "fallback_hourly_rate": {"type": "number"},
                    "fallback_hourly_rate_basis": {"type": "string"},
                    "rationale": {"type": "string"},
                  },
                  "required": [
                    "role_title",
                    "employee_count",
                    "hours_per_week",
                    "weeks_per_year",
                    "fallback_hourly_rate",
                    "fallback_hourly_rate_basis",
                    "rationale",
                  ],
                },
              },
            },
            "required": ["lob_key", "basis", "roles"],
          },
        }
      },
      "required": ["suggestions"],
    },
  }

  system = (
    "You propose a Year-1 headcount plan first so the client never has to invent numbers.\n"
    "Use industry/NAICS, stage, and operating context. Reflect ramp if pre-launch or very early.\n"
    "Do NOT ask open-ended questions like 'how many employees?'. Instead propose a plausible plan.\n"
    "Roles should be realistic and minimal: include only what is needed for Year 1.\n"
    "employee_count must be an integer >= 0. hours_per_week and weeks_per_year must be realistic.\n"
    "Also provide a fallback_hourly_rate per role based on NAICS/context, in case the wage dataset has no match.\n"
    "Return JSON only per the schema."
  )

  user = {
    "business_name": business_name,
    "business_type": business_type,
    "naics_6": naics_6,
    "today_iso": today_iso,
    "business_start_date": business_start_date,
    "lobs": lob_list,
    "ops": ops_json,
    "people": people_json,
    "shared_context": shared_context,
  }

  api_key = _require_openai_key()
  model = _openai_model()
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ],
    "response_format": {"type": "json_schema", "json_schema": schema},
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 300:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
  data = resp.json()
  parsed = _extract_output_json(data)
  suggestions = parsed.get("suggestions")
  if not isinstance(suggestions, list) or not suggestions:
    raise RuntimeError("Headcount proposer returned no suggestions.")

  cleaned: List[Dict[str, Any]] = []
  for s in suggestions:
    if not isinstance(s, dict):
      continue
    roles = s.get("roles")
    if not isinstance(roles, list) or not roles:
      continue
    roles_out: List[Dict[str, Any]] = []
    for r in roles:
      if not isinstance(r, dict):
        continue
      role_title = str(r.get("role_title") or "").strip()
      if not role_title:
        continue
      try:
        employee_count = int(r.get("employee_count") or 0)
      except Exception:
        employee_count = 0
      try:
        hpw = float(r.get("hours_per_week"))
      except Exception:
        hpw = 40.0
      try:
        wpy = float(r.get("weeks_per_year"))
      except Exception:
        wpy = 52.0
      try:
        fallback_rate = float(r.get("fallback_hourly_rate"))
      except Exception:
        fallback_rate = 0.0
      roles_out.append(
        {
          "role_title": role_title,
          "employee_count": max(0, employee_count),
          "hours_per_week": max(0.0, hpw),
          "weeks_per_year": max(0.0, wpy),
          "fallback_hourly_rate": max(0.0, fallback_rate),
          "fallback_hourly_rate_basis": str(r.get("fallback_hourly_rate_basis") or "").strip(),
          "rationale": str(r.get("rationale") or "").strip(),
        }
      )
    if not roles_out:
      continue
    cleaned.append(
      {
        "lob_key": str(s.get("lob_key") or "").strip() or "company_total",
        "lob_name": str(s.get("lob_name") or "").strip() or None,
        "basis": str(s.get("basis") or "").strip(),
        "roles": roles_out,
      }
    )

  return cleaned or []


def propose_revenue_suggestions(
  *,
  business_name: str,
  business_type: str,
  naics_6: Optional[str],
  today_iso: str,
  business_start_date: Optional[str],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  lobs: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
  """
  GPT-backed proposer for Revenue model drivers (proposal-first).

  Returns a list of suggestion dicts, each with:
    {lob_key, lob_name?, units_per_week_capacity, avg_units_per_week_year1, operating_weeks_per_year, unit_price, basis}
  """
  lob_list = []
  for lob in list(lobs or []):
    lk = str(lob.get("lob_key") or "").strip()
    if not lk or lk == "company_total":
      continue
    lob_list.append({"lob_key": lk, "lob_name": str(lob.get("lob_name") or "").strip()})
  if not lob_list:
    lob_list = [{"lob_key": "company_total", "lob_name": ""}]

  schema = {
    "name": "revenue_model_driver_proposer",
    "strict": True,
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "suggestions": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lob_key": {"type": "string"},
              "lob_name": {"type": ["string", "null"]},
              "units_per_week_capacity": {"type": "number"},
              "avg_units_per_week_year1": {"type": "number"},
              "operating_weeks_per_year": {"type": "number"},
              "unit_price": {"type": ["number", "null"]},
              "basis": {"type": "string"},
            },
            "required": [
              "lob_key",
              "units_per_week_capacity",
              "avg_units_per_week_year1",
              "operating_weeks_per_year",
              "unit_price",
              "basis",
            ],
          },
        }
      },
      "required": ["suggestions"],
    },
  }

  system = (
    "You propose revenue model assumptions first so the client never has to invent numbers.\n"
    "Use NAICS/industry context + what is already known + business start date/timing.\n"
    "If the business is pre-launch or very early, reflect a realistic ramp in Year 1.\n"
    "Do NOT ask open-ended questions like 'what is your revenue?' or 'what is your utilization?'.\n"
    "Return conservative, editable assumptions.\n"
    "If a single natural unit_price is not applicable (multi-stream), set unit_price to null.\n"
    "Return JSON only per the schema."
  )

  user = {
    "business_name": business_name,
    "business_type": business_type,
    "naics_6": naics_6,
    "today_iso": today_iso,
    "business_start_date": business_start_date,
    "lobs": lob_list,
    "ops": ops_json,
    "shared_context": shared_context,
  }

  api_key = _require_openai_key()
  model = _openai_model()
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ],
    "response_format": {"type": "json_schema", "json_schema": schema},
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 300:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
  data = resp.json()
  parsed = _extract_output_json(data)
  suggestions = parsed.get("suggestions")
  if not isinstance(suggestions, list) or not suggestions:
    raise RuntimeError("Revenue proposer returned no suggestions.")

  cleaned: List[Dict[str, Any]] = []
  for s in suggestions:
    if not isinstance(s, dict):
      continue
    cleaned.append(
      {
        "lob_key": str(s.get("lob_key") or "").strip() or "company_total",
        "lob_name": str(s.get("lob_name") or "").strip() or None,
        "units_per_week_capacity": float(s.get("units_per_week_capacity") or 0.0),
        "avg_units_per_week_year1": float(s.get("avg_units_per_week_year1") or 0.0),
        "operating_weeks_per_year": float(s.get("operating_weeks_per_year") or 52.0),
        "unit_price": (float(s.get("unit_price")) if s.get("unit_price") is not None else None),
        "basis": str(s.get("basis") or "").strip(),
      }
    )
  return cleaned or []


def propose_fulfillment_suggestions(
  *,
  business_name: str,
  business_type: str,
  naics_6: Optional[str],
  today_iso: str,
  business_start_date: Optional[str],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  lobs: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
  """
  GPT-backed proposer for Fulfillment model cards.

  Returns: {lob_key, lob_name?, fulfillment_model, who_fulfills, lead_time, basis}
  """
  lob_list = []
  for lob in list(lobs or []):
    lk = str(lob.get("lob_key") or "").strip()
    if not lk or lk == "company_total":
      continue
    lob_list.append({"lob_key": lk, "lob_name": str(lob.get("lob_name") or "").strip()})
  if not lob_list:
    lob_list = [{"lob_key": "company_total", "lob_name": ""}]

  schema = {
    "name": "fulfillment_model_card_proposer",
    "strict": True,
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "suggestions": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lob_key": {"type": "string"},
              "lob_name": {"type": ["string", "null"]},
              "fulfillment_model": {"type": "string"},
              "who_fulfills": {"type": "string"},
              "lead_time": {"type": "string"},
              "basis": {"type": "string"},
            },
            "required": ["lob_key", "fulfillment_model", "who_fulfills", "lead_time", "basis"],
          },
        }
      },
      "required": ["suggestions"],
    },
  }

  system = (
    "You propose a fulfillment model first so the client never has to invent operations wording.\n"
    "Use industry/NAICS and the current ops context.\n"
    "Keep it concrete, short, and editable.\n"
    "Return JSON only per the schema."
  )

  user = {
    "business_name": business_name,
    "business_type": business_type,
    "naics_6": naics_6,
    "today_iso": today_iso,
    "business_start_date": business_start_date,
    "lobs": lob_list,
    "ops": ops_json,
    "shared_context": shared_context,
  }

  api_key = _require_openai_key()
  model = _openai_model()
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ],
    "response_format": {"type": "json_schema", "json_schema": schema},
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 300:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
  data = resp.json()
  parsed = _extract_output_json(data)
  suggestions = parsed.get("suggestions")
  if not isinstance(suggestions, list) or not suggestions:
    raise RuntimeError("Fulfillment proposer returned no suggestions.")

  cleaned: List[Dict[str, Any]] = []
  for s in suggestions:
    if not isinstance(s, dict):
      continue
    cleaned.append(
      {
        "lob_key": str(s.get("lob_key") or "").strip() or "company_total",
        "lob_name": str(s.get("lob_name") or "").strip() or None,
        "fulfillment_model": str(s.get("fulfillment_model") or "").strip(),
        "who_fulfills": str(s.get("who_fulfills") or "").strip(),
        "lead_time": str(s.get("lead_time") or "").strip(),
        "basis": str(s.get("basis") or "").strip(),
      }
    )
  return cleaned or []


def propose_ops_concept_suggestions(
  *,
  business_name: str,
  business_type: str,
  naics_6: Optional[str],
  today_iso: str,
  business_start_date: Optional[str],
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  lobs: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
  """
  GPT-backed proposer for Ops-concept model cards.

  Returns: {lob_key, lob_name?, operating_unit, primary_constraint, process_overview, basis}
  """
  lob_list = []
  for lob in list(lobs or []):
    lk = str(lob.get("lob_key") or "").strip()
    if not lk or lk == "company_total":
      continue
    lob_list.append({"lob_key": lk, "lob_name": str(lob.get("lob_name") or "").strip()})
  if not lob_list:
    lob_list = [{"lob_key": "company_total", "lob_name": ""}]

  schema = {
    "name": "ops_concept_model_card_proposer",
    "strict": True,
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "suggestions": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lob_key": {"type": "string"},
              "lob_name": {"type": ["string", "null"]},
              "operating_unit": {"type": "string"},
              "primary_constraint": {"type": "string"},
              "process_overview": {"type": "string"},
              "basis": {"type": "string"},
            },
            "required": ["lob_key", "operating_unit", "primary_constraint", "process_overview", "basis"],
          },
        }
      },
      "required": ["suggestions"],
    },
  }

  system = (
    "You propose an operating concept first so the client does not have to write operations narrative.\n"
    "Keep it concise and structured: operating_unit, primary_constraint, and a short process_overview.\n"
    "Use NAICS/industry context + what is already known. Do not invent specific numbers.\n"
    "Return JSON only per the schema."
  )

  user = {
    "business_name": business_name,
    "business_type": business_type,
    "naics_6": naics_6,
    "today_iso": today_iso,
    "business_start_date": business_start_date,
    "lobs": lob_list,
    "ops": ops_json,
    "shared_context": shared_context,
  }

  api_key = _require_openai_key()
  model = _openai_model()
  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload: Dict[str, Any] = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ],
    "response_format": {"type": "json_schema", "json_schema": schema},
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 300:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
  data = resp.json()
  parsed = _extract_output_json(data)
  suggestions = parsed.get("suggestions")
  if not isinstance(suggestions, list) or not suggestions:
    raise RuntimeError("Ops-concept proposer returned no suggestions.")

  cleaned: List[Dict[str, Any]] = []
  for s in suggestions:
    if not isinstance(s, dict):
      continue
    cleaned.append(
      {
        "lob_key": str(s.get("lob_key") or "").strip() or "company_total",
        "lob_name": str(s.get("lob_name") or "").strip() or None,
        "operating_unit": str(s.get("operating_unit") or "").strip(),
        "primary_constraint": str(s.get("primary_constraint") or "").strip(),
        "process_overview": str(s.get("process_overview") or "").strip(),
        "basis": str(s.get("basis") or "").strip(),
      }
    )
  return cleaned or []
