import json
import os
import time
import calendar
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify
import requests

OPS_CONFIRM_QUESTION = "Does this look right before we move on to Target Market?"
MARKET_CONFIRM_QUESTION = "Does this look right before we move on to Human Resources?"
PEOPLE_CONFIRM_QUESTION = "Does this look right before we move on to Financials?"
FIN_CONFIRM_QUESTION = "Does this look right before we move on to Submit intake?"
COMPETITIVE_ADVANTAGE_PREFIX = "Proposed competitive advantage:"
COMPETITIVE_ADVANTAGE_QUESTION = "Does this accurately reflect what truly sets the business apart?"
_RETRYABLE_STATUS = {429, 502, 503, 504}


def _parse_json_dict(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _parse_messages(raw: Any) -> List[Dict[str, str]]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return [m for m in raw if isinstance(m, dict)]
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  return [m for m in parsed if isinstance(m, dict)] if isinstance(parsed, list) else []


def _last_assistant_message(messages: List[Dict[str, str]]) -> str:
  for msg in reversed(messages or []):
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    text = str(msg.get("content") or "").strip()
    if text:
      return text
  return ""


def _should_check_revenue_patch(last_assistant: str, user_message: str) -> bool:
  assistant = str(last_assistant or "").lower()
  if "year 1 revenue" in assistant or "year-1 revenue" in assistant:
    return True
  if "revenue math" in assistant:
    return True
  msg = str(user_message or "").lower()
  keywords = [
    "unit price",
    "price per",
    "units per week",
    "units/week",
    "units per month",
    "units/month",
    "per month",
    "monthly",
    "per contract",
    "contracts",
    "retainer",
    "weeks per year",
    "weeks/year",
    "periods per year",
    "periods/year",
    "utilization",
    "capacity",
    "product",
    "line of business",
    "lob",
  ]
  return any(k in msg for k in keywords)


def _extract_revenue_proposal_patch(
  *,
  last_assistant: str,
  route_intent,
  financials_year1_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  try:
    proposal_intent = route_intent(
      consult_type="financials_year1",
      user_message=text,
      baseline_json=financials_year1_json,
      shared_context=shared_context,
      recent_messages=[],
      active_focus="financials",
    )
  except Exception:
    return None
  if str(proposal_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = proposal_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  return patch


def _is_guardrail_acknowledgement(message: str) -> bool:
  text = str(message or "").strip().lower()
  if not text:
    return False
  try:
    import re

    patterns = [
      r"\bok\b",
      r"\bokay\b",
      r"\byes\b",
      r"\bsounds good\b",
      r"\blooks good\b",
      r"\bworks for me\b",
      r"\bgo ahead\b",
      r"\bproceed\b",
      r"\bkeep (it|this) (as is|the same)\b",
      r"\bkeep as is\b",
      r"\bleave it\b",
      r"\bno changes\b",
      r"\bno change\b",
      r"\bi understand\b",
      r"\bunderstood\b",
      r"\baccept\b",
      r"\bi'?m ok\b",
      r"\bi am ok\b",
      r"\bfine\b",
      r"\ball good\b",
    ]
    return any(re.search(pat, text) for pat in patterns)
  except Exception:
    return False


def _detect_confirm_question(last_assistant: str) -> Optional[str]:
  text = str(last_assistant or "").strip().lower()
  if not text:
    return None
  for question in (
    OPS_CONFIRM_QUESTION,
    MARKET_CONFIRM_QUESTION,
    PEOPLE_CONFIRM_QUESTION,
    FIN_CONFIRM_QUESTION,
  ):
    if question and question.lower() in text:
      return question
  return None


def _extract_competitive_advantage_prompt(last_assistant: str) -> Optional[str]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  for line in text.splitlines():
    line_stripped = line.strip()
    if not line_stripped:
      continue
    if line_stripped.lower().startswith(COMPETITIVE_ADVANTAGE_PREFIX.lower()):
      _, _, rest = line_stripped.partition(":")
      value = rest.strip()
      return value or None
  return None


def _finalize_flag_field(focus: str, value: bool) -> Optional[Dict[str, Any]]:
  focus_norm = str(focus or "").strip().lower()
  mapping = {
    "ops": "ops_finalize_proposed",
    "market": "market_finalize_proposed",
    "people": "people_finalize_proposed",
    "financials": "financials_finalize_proposed",
  }
  key = mapping.get(focus_norm)
  if not key:
    return None
  return {key: bool(value)}


def _year1_driver_map(year1_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  out: Dict[str, Dict[str, Any]] = {}
  if not isinstance(year1_json, dict):
    return out
  lobs = year1_json.get("lobs")
  if not isinstance(lobs, list):
    return out
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip().lower()
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip().lower()
      if not product_name:
        continue
      key = f"{lob_name}::{product_name}"
      out[key] = {
        "unit_cadence": str(product.get("unit_cadence") or "").strip().lower(),
        "unit_price": product.get("unit_price"),
        "units_per_period_capacity": product.get("units_per_period_capacity"),
      }
  return out


def _year1_drivers_conflict(existing_year1: Optional[Dict[str, Any]], base_year1: Dict[str, Any]) -> bool:
  if not isinstance(existing_year1, dict) or not existing_year1:
    return False
  existing_map = _year1_driver_map(existing_year1)
  base_map = _year1_driver_map(base_year1)
  if not existing_map or not base_map:
    return False

  def _num(value: Any) -> Optional[float]:
    try:
      return float(value)
    except Exception:
      return None

  for key, base_driver in base_map.items():
    existing_driver = existing_map.get(key)
    if not existing_driver:
      continue
    base_cadence = str(base_driver.get("unit_cadence") or "").strip().lower()
    existing_cadence = str(existing_driver.get("unit_cadence") or "").strip().lower()
    if base_cadence and existing_cadence and base_cadence != existing_cadence:
      return True
    base_price = _num(base_driver.get("unit_price"))
    existing_price = _num(existing_driver.get("unit_price"))
    if base_price is not None and existing_price is not None and abs(base_price - existing_price) > 0.01:
      return True
    base_capacity = _num(base_driver.get("units_per_period_capacity"))
    existing_capacity = _num(existing_driver.get("units_per_period_capacity"))
    if base_capacity is not None and existing_capacity is not None and abs(base_capacity - existing_capacity) > 0.01:
      return True
  return False


def _normalize_unscoped_patch(patch: Dict[str, Any], *, focus: str) -> Dict[str, Any]:
  focus_norm = str(focus or "").strip().lower()
  if not isinstance(patch, dict) or not patch:
    return patch
  field_sets = {
    "ops": {
      "consumer_type",
      "business_type",
      "business_stage",
      "business_naics_6",
      "unit_name",
      "unit_description",
      "unit_cadence",
      "units_per_week_capacity",
      "units_per_period_capacity",
      "unit_price",
      "shipping_method",
      "sales_modality",
      "geographic_scope",
      "geographic_coverage",
      "countries",
      "milestones",
      "competitive_advantage",
      "capacity_driver",
      "primary_growth_lever",
      "legal_entity",
      "lob_models",
      "confidence",
    },
    "market": {
      "consumer_type",
      "gender_age_intent",
      "income_intent",
      "selections",
      "b2b_industry_terms",
      "b2b_naics_6",
      "b2b_size_bands",
      "b2b_age_bands",
      "marketing_plan_summary",
      "confidence",
    },
    "people": {
      "people",
      "inferred_roles",
      "inferred_roles_summary",
      "business_naics_6",
      "confidence",
    },
    "financials": {
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
    },
    "fulfillment": {
      "time",
      "personnel",
    },
  }
  allowed = field_sets.get(focus_norm, set())
  if not allowed:
    return patch
  normalized: Dict[str, Any] = {}
  for raw_key, value in patch.items():
    key = str(raw_key or "").strip()
    if not key:
      continue
    if "." in key:
      normalized[key] = value
      continue
    if key in allowed:
      normalized[f"{focus_norm}.{key}"] = value
    else:
      normalized[key] = value
  return normalized

def _constraints_snippet_already_sent(messages: List[Dict[str, str]]) -> bool:
  for msg in messages or []:
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    content = str(msg.get("content") or "")
    if "operational constraints:" in content.lower():
      return True
  return False


def _append_constraints_snippet(
  assistant_text: str,
  snippet: str,
  messages: List[Dict[str, str]],
  *,
  force: bool = False,
) -> str:
  if not snippet:
    return assistant_text
  if "operational constraints:" in str(assistant_text or "").lower():
    return assistant_text
  if _constraints_snippet_already_sent(messages):
    return assistant_text
  if not force:
    return assistant_text
  if not assistant_text:
    return snippet
  return f"{assistant_text}\n\n{snippet}".strip()



def _strip_acs_codes(text: str) -> str:
  """
  Never expose raw ACS codes in the UI conversation.
  """
  try:
    import re

    return re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "[ACS code redacted]", text)
  except Exception:
    return text


def _parse_date(value: Any) -> Optional[date]:
  if value is None:
    return None
  if isinstance(value, datetime):
    return value.date()
  if isinstance(value, date):
    return value
  raw = str(value).strip()
  if not raw:
    return None
  try:
    return datetime.fromisoformat(raw).date()
  except ValueError:
    pass
  for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
    try:
      return datetime.strptime(raw, fmt).date()
    except ValueError:
      continue
  return None


def _infer_business_stage(start_date_raw: Any, current_date: Optional[date] = None) -> Optional[str]:
  start_date = _parse_date(start_date_raw)
  if start_date is None:
    return None
  today = current_date or datetime.utcnow().date()
  if start_date > today:
    return "pre-revenue"
  delta_days = (today - start_date).days
  if delta_days <= 365:
    return "early-stage"
  return "operating"


def _openai_key() -> Optional[str]:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  return key or None


def _openai_model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _openai_timeout_seconds() -> int:
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
  chunks: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        chunks.append(str(part["text"]))
  if not chunks:
    raise RuntimeError("OpenAI response contained no output_text.")
  return "\n".join(chunks).strip()


def _months_until(target: date, reference_date: Optional[date]) -> int:
  ref = reference_date or datetime.utcnow().date()
  months = (target.year - ref.year) * 12 + (target.month - ref.month)
  if target.day > ref.day:
    months += 1
  if months < 0:
    return 0
  return months


def _timing_months_max_deterministic(timing_text: str, reference_date: Optional[date]) -> Optional[int]:
  text = str(timing_text or "").strip().lower()
  if not text:
    return None
  try:
    import re

    months_match = re.search(r"\b(\d+)\s*(months?|mos?)\b", text)
    if months_match:
      return int(months_match.group(1))
    years_match = re.search(r"\b(\d+)\s*(years?|yrs?)\b", text)
    if years_match:
      return int(years_match.group(1)) * 12

    quarter_match = re.search(r"\bq([1-4])\s*([12]\d{3})\b", text)
    if quarter_match:
      q = int(quarter_match.group(1))
      year = int(quarter_match.group(2))
      month = q * 3
      last_day = calendar.monthrange(year, month)[1]
      return _months_until(date(year, month, last_day), reference_date)
    quarter_match = re.search(r"\b([12]\d{3})\s*q([1-4])\b", text)
    if quarter_match:
      year = int(quarter_match.group(1))
      q = int(quarter_match.group(2))
      month = q * 3
      last_day = calendar.monthrange(year, month)[1]
      return _months_until(date(year, month, last_day), reference_date)

    month_map = {
      "jan": 1,
      "january": 1,
      "feb": 2,
      "february": 2,
      "mar": 3,
      "march": 3,
      "apr": 4,
      "april": 4,
      "may": 5,
      "jun": 6,
      "june": 6,
      "jul": 7,
      "july": 7,
      "aug": 8,
      "august": 8,
      "sep": 9,
      "sept": 9,
      "september": 9,
      "oct": 10,
      "october": 10,
      "nov": 11,
      "november": 11,
      "dec": 12,
      "december": 12,
    }
    month_regex = r"\b(" + "|".join(month_map.keys()) + r")\b"
    month_match = re.search(month_regex + r".*?\b([12]\d{3})\b", text)
    if month_match:
      month_name = month_match.group(1)
      year = int(month_match.group(2))
      month = month_map.get(month_name)
      if month:
        last_day = calendar.monthrange(year, month)[1]
        return _months_until(date(year, month, last_day), reference_date)

    year_end_match = re.search(r"(end of|by end of)\s*([12]\d{3})\b", text)
    if year_end_match:
      year = int(year_end_match.group(2))
      return _months_until(date(year, 12, 31), reference_date)
  except Exception:
    return None
  return None


def _timing_months_max_via_openai(timing_text: str, reference_date: Optional[date]) -> Optional[int]:
  key = _openai_key()
  if not key:
    return None
  timing = str(timing_text or "").strip()
  if timing:
    timing = timing.replace("\u2013", "-").replace("\u2014", "-")
  if not timing:
    return None
  ref_date = reference_date.isoformat() if isinstance(reference_date, date) else None
  system = (
    "You convert milestone timing text into a single integer: the MAX number of months. "
    "If the text contains a range, return the upper bound in months. "
    "If the text references quarters or years, convert to months. "
    "If you cannot determine a number of months, return null. "
    "Return ONLY valid JSON: {\"months_max\": <integer or null>}."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps({"timing": timing, "reference_date": ref_date})},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return None
  data = resp.json()
  raw = _parse_responses_text(data)
  try:
    parsed = json.loads(raw)
  except Exception:
    parsed = None
  if isinstance(parsed, dict):
    value = parsed.get("months_max")
  else:
    value = raw.strip()
  if value is None:
    return None
  if isinstance(value, (int, float)):
    return int(round(float(value)))
  try:
    return int(round(float(str(value).strip())))
  except Exception:
    return None


def _enrich_milestones_timing(ops_json: Dict[str, Any], reference_date: Optional[date]) -> None:
  milestones = ops_json.get("milestones")
  if isinstance(milestones, str):
    try:
      milestones = json.loads(milestones)
    except Exception:
      milestones = None
  if not isinstance(milestones, list):
    return
  def _coerce_positive_int(value: Any) -> Optional[int]:
    if value is None:
      return None
    if isinstance(value, bool):
      return None
    if isinstance(value, (int, float)):
      if float(value) <= 0:
        return None
      return int(round(float(value)))
    try:
      parsed = int(round(float(str(value).strip())))
    except Exception:
      return None
    return parsed if parsed > 0 else None

  for milestone in milestones:
    if not isinstance(milestone, dict):
      continue
    existing = _coerce_positive_int(milestone.get("timing_months_max"))
    if existing is not None:
      milestone["timing_months_max"] = existing
      continue
    months = _timing_months_max_deterministic(str(milestone.get("timing") or "").strip(), reference_date)
    if months is None:
      months = _timing_months_max_via_openai(str(milestone.get("timing") or "").strip(), reference_date)
    if months is None:
      continue
    milestone["timing_months_max"] = months


def _parse_milestones(raw: Any) -> List[Dict[str, Any]]:
  if raw is None:
    return []
  if isinstance(raw, str):
    try:
      parsed = json.loads(raw)
    except Exception:
      return []
    raw = parsed
  if not isinstance(raw, list):
    return []
  return [m for m in raw if isinstance(m, dict)]


def _has_confirmed_milestone(ops_json: Dict[str, Any]) -> bool:
  for milestone in _parse_milestones((ops_json or {}).get("milestones")):
    desc = str(milestone.get("description") or "").strip()
    timing = str(milestone.get("timing") or "").strip()
    if desc and timing:
      return True
  return False


def _ensure_ops_business_naics(conn, ops_json: Dict[str, Any]) -> None:
  if not isinstance(ops_json, dict):
    return
  if not ops_json.get("business_type"):
    return
  if ops_json.get("business_naics_6"):
    return
  try:
    try:
      from intake_business_types import get_naics_from_business_type  # type: ignore
    except Exception:
      from client_intake_and_finmo.intake_business_types import (  # type: ignore
        get_naics_from_business_type,
      )
    ops_json["business_naics_6"] = get_naics_from_business_type(
      conn, ops_json.get("business_type")
    )
  except Exception:
    ops_json.setdefault("business_naics_6", None)


def _extract_ops_pending_milestone(
  *,
  text: str,
  route_intent,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
  try:
    milestone_intent = route_intent(
      consult_type="ops",
      user_message=str(text or "").strip(),
      baseline_json=ops_json,
      shared_context=shared_context,
      recent_messages=[],
      active_focus="ops",
    )
  except Exception:
    return None
  if str(milestone_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = milestone_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  milestones_val = patch.get("milestones")
  if not milestones_val:
    return None
  if isinstance(milestones_val, str):
    try:
      milestones_val = json.loads(milestones_val)
    except Exception:
      return None
  if not isinstance(milestones_val, list):
    return None
  return [m for m in milestones_val if isinstance(m, dict)]

def _propose_ops_competitive_advantage(
  *,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> str:
  key = _openai_key()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  system = (
    "You are a senior business consultant defining a company’s competitive advantage.\n\n"
    "This is NOT marketing language.\n"
    "This is an execution-based advantage grounded in how the business actually operates.\n\n"
    "Context:\n"
    "You are given the full operating model, including:\n"
    "- business type and stage\n"
    "- unit definition and pricing\n"
    "- capacity driver (labor / system / demand)\n"
    "- fulfillment and delivery model\n"
    "- geographic scope and coverage\n"
    "- target customer type (consumer / B2B / mixed)\n\n"
    "Your task:\n"
    "Propose ONE concise competitive advantage that clearly explains:\n"
    "1) What this business does meaningfully differently from typical competitors\n"
    "2) Why that difference exists operationally (process, structure, constraints, choices)\n"
    "3) Why it matters economically or experientially to the customer\n"
    "4) Why it is not trivial for competitors to replicate\n\n"
    "Hard rules:\n"
    "- Do NOT use generic phrases (e.g., “high quality,” “great service,” “customer-focused,” “fast,” “personalized”) unless you explain *how* they are structurally enabled.\n"
    "- Do NOT describe multiple advantages — pick the single most defensible one.\n"
    "- Do NOT restate the business description.\n"
    "- Tie the advantage to at least ONE concrete operational choice (e.g., menu design, staffing model, throughput discipline, geographic focus, fulfillment cadence).\n"
    "- Keep it to 2–3 sentences total.\n\n"
    "After proposing the advantage, ask ONE confirmation question:\n"
    "“Does this accurately reflect what truly sets the business apart?”\n\n"
    "If the client disagrees:\n"
    "- Ask ONE targeted clarification question.\n"
    "- Revise the advantage once and ask for confirmation again."
  )
  context_payload = {
    "business": {
      "name": business_facts.get("name"),
      "start_date": business_facts.get("start_date"),
      "address": business_facts.get("address"),
    },
    "ops": ops_json,
    "shared_context": shared_context or {},
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(context_payload)},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    raise RuntimeError(_format_openai_error(resp))
  data = resp.json()
  raw = _parse_responses_text(data)
  cleaned = " ".join(str(raw or "").split()).strip().strip('"')
  if not cleaned:
    raise RuntimeError("Failed to generate competitive advantage.")
  question = COMPETITIVE_ADVANTAGE_QUESTION
  lower = cleaned.lower()
  q_lower = question.lower()
  if q_lower in lower:
    idx = lower.rfind(q_lower)
    cleaned = cleaned[:idx].strip()
  if not cleaned:
    raise RuntimeError("Failed to generate competitive advantage.")
  return cleaned


def _build_business_type_candidates(*, conn, messages: List[Dict[str, str]]) -> List[str]:
  """
  Build a small, relevant business_type candidate list by scoring known values against
  early user messages. This keeps finalization deterministic while avoiding a huge list.
  """
  try:
    from difflib import SequenceMatcher

    cur = conn.cursor()
    try:
      cur.execute("SELECT business_types FROM naics_master WHERE business_types IS NOT NULL")
      rows = cur.fetchall() or []
      values: List[str] = []
      for (bt,) in rows:
        if bt is None:
          continue
        for part in str(bt).split(","):
          part_str = str(part).strip()
          if part_str:
            values.append(part_str)
      all_business_types = sorted(set(values), key=lambda x: x.lower())
    finally:
      try:
        cur.close()
      except Exception:
        pass

    user_texts: List[str] = []
    for msg in messages:
      if str(msg.get("role") or "") != "user":
        continue
      content = str(msg.get("content") or "").strip()
      if not content:
        continue
      # Ignore internal-start markers if present.
      if "Start the operational intake." in content:
        continue
      user_texts.append(content)
      if len(user_texts) >= 6:
        break

    base = " ".join(user_texts).strip().lower()
    base = " ".join(base.split())
    tokens = {t for t in base.replace("/", " ").replace("-", " ").split() if len(t) >= 3}

    scored = []
    for bt in all_business_types:
      btl = bt.lower()
      token_score = sum(1 for t in tokens if t in btl) if tokens else 0
      ratio = SequenceMatcher(None, base, btl).ratio() if base else 0.0
      scored.append((token_score, ratio, bt))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [bt for _, _, bt in scored[:80]] or (all_business_types[:80] if all_business_types else [])
  except Exception:
    return []


def _normalize_business_type_from_candidates(
  raw_value: Any, candidates: List[str]
) -> Any:
  """
  Normalize a business_type value to the closest candidate label (case-insensitive).
  Falls back to the raw value if no candidates are available.
  """
  raw = str(raw_value or "").strip()
  if not raw or not candidates:
    return raw_value
  raw_lower = raw.lower()
  for candidate in candidates:
    if str(candidate or "").strip().lower() == raw_lower:
      return candidate
  try:
    from difflib import SequenceMatcher

    best = None
    best_score = 0.0
    for candidate in candidates:
      cand = str(candidate or "").strip()
      if not cand:
        continue
      score = SequenceMatcher(None, raw_lower, cand.lower()).ratio()
      if score > best_score:
        best_score = score
        best = cand
    return best if best else raw_value
  except Exception:
    return raw_value


def _compute_focus_and_confirm_question(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  ops_confirmed: bool,
  market_confirmed: bool,
  people_confirmed: bool,
  financials_confirmed: bool,
  consistency_passed: bool,
) -> Tuple[str, Optional[str]]:
  # No realtime missing-fields gating; progression follows confirmations in order.
  if not ops_confirmed:
    return ("ops", None)
  if not market_confirmed:
    return ("market", None)
  if not people_confirmed:
    return ("people", None)
  if not financials_confirmed:
    return ("financials", None)
  if not consistency_passed:
    return ("consistency", None)
  return ("done", None)


def _next_focus(current: str) -> str:
  order = ["ops", "market", "people", "financials", "consistency", "done"]
  cur = str(current or "").strip().lower()
  if cur not in order:
    return "ops"
  idx = order.index(cur)
  return order[min(idx + 1, len(order) - 1)]


def _start_instruction_for_focus(focus: str) -> str:
  focus_norm = str(focus or "").strip().lower()
  if focus_norm == "ops":
    return "Start the operational intake. Ask your first question."
  if focus_norm == "market":
    return "Start the target market intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."
  if focus_norm == "people":
    return "Start the People & Capability intake. Ask your first question."
  if focus_norm == "financials":
    return "Start the financials intake. Ask your first question."
  if focus_norm == "consistency":
    return "Start the consistency check. Review the current intake model and ask your first clarifying question."
  return "Continue."


def _apply_scoped_patch(
  patch: Dict[str, Any],
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  """
  Apply patch keys scoped as "<group>.<field>" into the canonical section objects.
  """
  next_business = dict(business_facts)
  next_ops = dict(ops_json)
  next_market = dict(market_json)
  next_people = dict(people_json)
  next_financials = dict(financials_json)
  next_fulfillment = dict(fulfillment_json)

  for raw_key, value in (patch or {}).items():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    group, field = key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    if not group or not field:
      continue

    if group == "business":
      next_business[field] = value
      if field == "address":
        # If the canonical address string changes via chat-driven patch, we do not
        # have reliable structured parts (street/city/state/zip/country). Clear
        # parts so the UI can prompt the client to re-select a full address from
        # suggestions before final submit.
        for part_key in (
          "address_street",
          "address_city",
          "address_state",
          "address_zip",
          "address_country",
        ):
          next_business[part_key] = None
    elif group == "ops":
      next_ops[field] = value
    elif group == "market":
      next_market[field] = value
    elif group == "people":
      next_people[field] = value
    elif group == "financials":
      next_financials[field] = value
    elif group == "fulfillment":
      next_fulfillment[field] = value

  return next_business, next_ops, next_market, next_people, next_financials, next_fulfillment


def _fetch_target_market_mapping_rows(conn) -> List[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT acs_code, description, segment, min_value, max_value FROM target_market_mapping"
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  def _parse_nullable_float(value: Any) -> Any:
    if value is None or value == "":
      return None
    try:
      return float(value)
    except Exception:
      return None

  mapping_rows: List[Dict[str, Any]] = []
  for r in rows:
    if not isinstance(r, dict):
      continue
    mapping_rows.append(
      {
        "acs_code": str(r.get("acs_code") or "").strip(),
        "description": str(r.get("description") or "").strip(),
        "segment": str(r.get("segment") or "").strip(),
        "min_value": _parse_nullable_float(r.get("min_value")),
        "max_value": _parse_nullable_float(r.get("max_value")),
      }
    )

  allowed_segments = {
    "Gender & Age",
    "Income",
    "Education",
    "Household Structure",
    "Housing Economics",
    "Employment",
  }

  cleaned: List[Dict[str, Any]] = []
  for r in mapping_rows:
    if not r["acs_code"] or not r["segment"]:
      continue
    if r["segment"] not in allowed_segments:
      continue
    # Ignore "Total households" rows for household structure selection.
    if r["segment"] == "Household Structure":
      desc_norm = " ".join(str(r["description"]).split()).strip().lower()
      if desc_norm == "total households":
        continue
    cleaned.append(r)
  if not cleaned:
    raise RuntimeError(
      "target_market_mapping table is empty; load it before running the target market consult."
    )
  return cleaned


def post_intake_consult_session_handler(*, app, request):
  """
  Create a new durable unified intake draft and return {draft_id, client_id}.
  """
  if request.method == "OPTIONS":
    return ("", 204)

  try:
    from intake_submission import generate_client_id, get_mysql_connection  # type: ignore
    from intake_consult_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import intake consult draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  client_id = generate_client_id()
  conn = get_mysql_connection()
  try:
    draft = create_draft(conn, client_id=client_id)
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
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
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
    except Exception as exc:
      return (jsonify({"error": "not_found", "detail": str(exc)}), 404)

    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
        "draft_status": draft.get("status"),
        "active_focus": draft.get("active_focus"),
        "ops_confirmed": bool(draft.get("ops_confirmed")),
        "market_confirmed": bool(draft.get("market_confirmed")),
        "people_confirmed": bool(draft.get("people_confirmed")),
        "financials_confirmed": bool(draft.get("financials_confirmed")),
        "consistency_passed": bool(draft.get("consistency_passed")),
        "business_name": draft.get("business_name"),
        "business_address": draft.get("business_address"),
        "address_street": draft.get("address_street"),
        "address_city": draft.get("address_city"),
        "address_state": draft.get("address_state"),
        "address_zip": draft.get("address_zip"),
        "address_country": draft.get("address_country"),
        "business_start_date": draft.get("business_start_date"),
        "messages_json": draft.get("messages_json"),
        "operating_model_json": draft.get("operating_model_json"),
        "target_market_json": draft.get("target_market_json"),
        "people_json": draft.get("people_json"),
        "financials_json": draft.get("financials_json"),
        "financials_year1_json": draft.get("financials_year1_json"),
        "fulfillment_json": draft.get("fulfillment_json"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def post_intake_consult_handler(*, app, request):
  """
  Unified intake consult controller (single chat, single draft model).
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  raw_message = payload.get("message")
  message = str(raw_message or "").strip()
  starting = raw_message is None or not message

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import append_messages, get_draft  # type: ignore
    from api_handlers.shared_context import build_shared_context  # type: ignore
    from fact_templates import sanitize_fact_template  # type: ignore
    from intent_router import route_intent  # type: ignore

    from intake_consultant import consultant_chat_turn, consultant_finalize  # type: ignore
    from target_market_consultant import target_market_chat_turn, target_market_finalize  # type: ignore
    from people_capability_consultant import (  # type: ignore
      people_capability_chat_turn,
      people_capability_finalize,
    )
    from financials_consultant import financials_chat_turn, financials_finalize  # type: ignore
    from financials_year1 import (  # type: ignore
      assemble_financials_year1,
      apply_revenue_driver_patch,
      build_revenue_driver_signature,
      build_revenue_guardrail_signals,
      build_revenue_constraints_snippet,
      build_revenue_math_line,
    )
    from consistency_consultant import consistency_chat_turn  # type: ignore
    from api_handlers.fact_propagation import propagate_shared_facts
    from api_handlers.revenue_guardrail_state import acknowledge_signature, get_acknowledged_signature
  except Exception as exc:
    app.logger.exception("Failed to import unified intake helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    consult = get_draft(conn, draft_id=str(draft_id).strip())
    client_id = str(consult.get("client_id") or "").strip()
    draft_status = str(consult.get("status") or "").strip().lower()
    if draft_status == "submitted":
      return (
        jsonify({"error": "duplicate_submit", "detail": "This draft was already submitted."}),
        409,
      )

    messages = _parse_messages(consult.get("messages_json"))

    ops_json = _parse_json_dict(consult.get("operating_model_json"))
    market_json = _parse_json_dict(consult.get("target_market_json"))
    people_json = _parse_json_dict(consult.get("people_json"))
    financials_json = _parse_json_dict(consult.get("financials_json"))
    financials_year1_json = _parse_json_dict(consult.get("financials_year1_json"))
    fulfillment_json = _parse_json_dict(consult.get("fulfillment_json"))
    pending_ops_milestone = _parse_milestones(consult.get("pending_ops_milestone_json"))

    _ensure_ops_business_naics(conn, ops_json)

    ops_confirmed = bool(consult.get("ops_confirmed"))
    market_confirmed = bool(consult.get("market_confirmed"))
    people_confirmed = bool(consult.get("people_confirmed"))
    financials_confirmed = bool(consult.get("financials_confirmed"))
    consistency_passed = bool(consult.get("consistency_passed"))
    ops_finalize_proposed = bool(consult.get("ops_finalize_proposed"))
    market_finalize_proposed = bool(consult.get("market_finalize_proposed"))
    people_finalize_proposed = bool(consult.get("people_finalize_proposed"))
    financials_finalize_proposed = bool(consult.get("financials_finalize_proposed"))

    business_facts: Dict[str, Any] = {
      "name": consult.get("business_name"),
      "address": consult.get("business_address"),
      "start_date": consult.get("business_start_date"),
      "address_street": consult.get("address_street"),
      "address_city": consult.get("address_city"),
      "address_state": consult.get("address_state"),
      "address_zip": consult.get("address_zip"),
      "address_country": consult.get("address_country"),
    }

    # Allow explicit client-detail updates from the UI (no intent inference).
    if payload.get("business_name") is not None:
      name_raw = str(payload.get("business_name") or "").strip()
      if name_raw:
        business_facts["name"] = name_raw
    address_keys = ("address_street", "address_city", "address_state", "address_zip", "address_country")
    payload_parts: Dict[str, str] = {}
    for key in address_keys:
      if payload.get(key) is None:
        payload_parts[key] = ""
        continue
      payload_parts[key] = str(payload.get(key) or "").strip()
    has_all_parts = all(payload_parts.values())
    if payload.get("address") is not None:
      addr_raw = str(payload.get("address") or "").strip()
      if addr_raw and has_all_parts:
        business_facts["address"] = addr_raw
    start_date_raw = payload.get("business_start_date")
    if start_date_raw is None:
      start_date_raw = payload.get("businessStartDate") or payload.get("business_startDate")
    if start_date_raw is not None:
      sd_raw = str(start_date_raw or "").strip()
      if sd_raw:
        business_facts["start_date"] = sd_raw

    if has_all_parts:
      for key, val in payload_parts.items():
        if val:
          business_facts[key] = val

    current_date = datetime.utcnow().date()
    current_date_iso = current_date.isoformat()
    business_stage_hint = _infer_business_stage(business_facts.get("start_date"), current_date)

    focus, confirm_question = _compute_focus_and_confirm_question(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      ops_confirmed=ops_confirmed,
      market_confirmed=market_confirmed,
      people_confirmed=people_confirmed,
      financials_confirmed=financials_confirmed,
      consistency_passed=consistency_passed,
    )

    shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
    shared_context = dict(shared_context or {})
    shared_context["operating_model"] = ops_json
    shared_context["target_market"] = market_json
    shared_context["people_capability"] = people_json
    shared_context["financials"] = financials_json
    base_year1 = assemble_financials_year1(shared_context, None)
    if _year1_drivers_conflict(financials_year1_json, base_year1):
      financials_year1_json = base_year1
    else:
      financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
    if isinstance(financials_year1_json, dict) and financials_year1_json:
      shared_context["financials_year1_json"] = financials_year1_json
    revenue_math_line = build_revenue_math_line(
      financials_year1_json,
      unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
    )
    revenue_constraints_snippet = build_revenue_constraints_snippet(
      shared_context,
      financials_year1_json,
      business_start_date=str(business_facts.get("start_date") or "").strip() or None,
    )
    guardrail_signals = build_revenue_guardrail_signals(
      shared_context,
      financials_year1_json,
      business_start_date=str(business_facts.get("start_date") or "").strip() or None,
      fulfillment_context=fulfillment_json,
    )
    driver_signature = build_revenue_driver_signature(financials_year1_json)
    guardrail_acknowledged = (
      get_acknowledged_signature(str(draft_id).strip()) == driver_signature
    )
    guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged

    if starting:
      start_instruction = _start_instruction_for_focus(focus)
      turn_messages = [*messages, {"role": "user", "content": start_instruction}]
      intake_context: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "fulfillment_json": fulfillment_json,
      }
      if focus == "market":
        consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
        if consumer_type not in ("consumer", "b2b", "mixed"):
          consumer_type = "consumer"
        intake_context["consumer_type"] = consumer_type
      intake_context["financials_year1_json"] = financials_year1_json
      intake_context["revenue_math_line"] = revenue_math_line
      intake_context["revenue_constraints_snippet"] = revenue_constraints_snippet
      intake_context["revenue_driver_patch"] = None
      intake_context["revenue_guardrail_triggered"] = guardrail_triggered
      intake_context["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
      intake_context["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

      if focus == "ops":
        assistant_text = consultant_chat_turn(
          intake_context=intake_context, conversation_messages=turn_messages
        )["assistant_message"]
      elif focus == "market":
        assistant_text = target_market_chat_turn(
          intake_context=intake_context, conversation_messages=turn_messages
        )["assistant_message"]
      elif focus == "people":
        assistant_text = people_capability_chat_turn(
          intake_context=intake_context, conversation_messages=turn_messages
        )["assistant_message"]
      elif focus == "financials":
        assistant_text = financials_chat_turn(
          intake_context=intake_context, conversation_messages=turn_messages
        )["assistant_message"]
      elif focus == "consistency":
        assistant_text = consistency_chat_turn(
          intake_context=intake_context, conversation_messages=turn_messages
        )["assistant_message"]
      else:
        assistant_text = "Continue."

      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      if focus == "financials":
        assistant_text = _append_constraints_snippet(
          assistant_text,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[{"role": "assistant", "content": assistant_text}],
        active_focus=focus,
        business_facts=business_facts,
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": bool(focus == "done"),
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    user_msg = {"role": "user", "content": message}
    recent_messages = messages[-12:] if len(messages) > 12 else list(messages)
    last_assistant = _last_assistant_message(messages)
    revenue_driver_patch = None
    pending_competitive_advantage = _extract_competitive_advantage_prompt(last_assistant)
    competitive_intent_override: Optional[Dict[str, Any]] = None
    if (
      pending_competitive_advantage
      and str(focus).strip().lower() == "ops"
      and not str((ops_json or {}).get("competitive_advantage") or "").strip()
    ):
      competitive_intent = route_intent(
        consult_type="ops",
        user_message=message,
        baseline_json=ops_json,
        shared_context=shared_context,
        recent_messages=recent_messages,
        confirm_question_override=COMPETITIVE_ADVANTAGE_QUESTION,
        active_focus="ops",
      )
      comp_action = str(competitive_intent.get("action") or "").strip()
      comp_router_msg = sanitize_fact_template(
        str(competitive_intent.get("assistant_message") or "").strip()
      )
      comp_patch = competitive_intent.get("patch") if isinstance(competitive_intent.get("patch"), dict) else None
      if comp_action == "confirm_clarify":
        assistant_text = comp_router_msg
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          active_focus=focus,
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": focus,
            "awaiting_confirmation": True,
            "done": False,
            "action": "confirm_clarify",
            "assistant_message": assistant_text,
          }
        )
      if comp_action == "confirm_proceed":
        comp_action = "edit_patch"
        comp_patch = {
          "competitive_advantage": sanitize_fact_template(
            str(pending_competitive_advantage or "").strip()
          )
        }
      if comp_action != "edit_patch":
        raise RuntimeError("Unexpected intent action for competitive advantage.")
      competitive_intent_override = {
        "action": comp_action,
        "router_msg": comp_router_msg,
        "patch": comp_patch,
      }

    if not starting:
      should_check_revenue = _should_check_revenue_patch(last_assistant, message) or guardrail_triggered
      if should_check_revenue:
        revenue_intent = route_intent(
          consult_type="financials_year1",
          user_message=message,
          baseline_json=financials_year1_json,
          shared_context=shared_context,
          recent_messages=recent_messages,
          active_focus="financials",
        )
        action = str(revenue_intent.get("action") or "").strip()
        patch = None
        if action == "edit_patch":
          patch = revenue_intent.get("patch")
        elif action == "confirm_proceed":
          patch = _extract_revenue_proposal_patch(
            last_assistant=last_assistant,
            route_intent=route_intent,
            financials_year1_json=financials_year1_json,
            shared_context=shared_context,
          )
        if isinstance(patch, dict) and patch:
          before_year1 = json.loads(json.dumps(financials_year1_json, ensure_ascii=False))
          revenue_driver_patch = patch
          financials_year1_json = apply_revenue_driver_patch(financials_year1_json, patch)
          updated_consults, propagated = propagate_shared_facts(
            source_consult_type="financials_year1",
            before_json=before_year1,
            after_json=financials_year1_json,
            consult_jsons={
              "ops": ops_json,
              "target_market": market_json,
              "people": people_json,
              "financials": financials_json,
              "financials_year1": financials_year1_json,
            },
          )
          ops_json = updated_consults.get("ops") or ops_json
          market_json = updated_consults.get("target_market") or market_json
          people_json = updated_consults.get("people") or people_json
          financials_json = updated_consults.get("financials") or financials_json
          financials_year1_json = (
            updated_consults.get("financials_year1") or financials_year1_json
          )
          if propagated:
            shared_context["operating_model"] = ops_json
            shared_context["target_market"] = market_json
            shared_context["people_capability"] = people_json
            shared_context["financials"] = financials_json
            shared_context["financials_year1"] = financials_year1_json

          revenue_constraints_snippet = build_revenue_constraints_snippet(
            shared_context,
            financials_year1_json,
            business_start_date=str(business_facts.get("start_date") or "").strip() or None,
          )
          guardrail_signals = build_revenue_guardrail_signals(
            shared_context,
            financials_year1_json,
            business_start_date=str(business_facts.get("start_date") or "").strip() or None,
            fulfillment_context=fulfillment_json,
          )
          driver_signature = build_revenue_driver_signature(financials_year1_json)
          guardrail_acknowledged = (
            get_acknowledged_signature(str(draft_id).strip()) == driver_signature
          )
          guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged
          if guardrail_triggered:
            acknowledge_signature(str(draft_id).strip(), driver_signature)
            guardrail_triggered = False

    if (
      guardrail_triggered
      and not revenue_driver_patch
      and not starting
      and _is_guardrail_acknowledgement(message)
    ):
      acknowledge_signature(str(draft_id).strip(), driver_signature)
      guardrail_triggered = False

    revenue_math_line = build_revenue_math_line(
      financials_year1_json,
      unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
    )

    focus, confirm_question = _compute_focus_and_confirm_question(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      ops_confirmed=ops_confirmed,
      market_confirmed=market_confirmed,
      people_confirmed=people_confirmed,
      financials_confirmed=financials_confirmed,
      consistency_passed=consistency_passed,
    )

    baseline_json = {
      "business": business_facts,
      "ops": ops_json,
      "market": market_json,
      "people": people_json,
      "financials": financials_json,
      "fulfillment": fulfillment_json,
    }
    shared_context_for_router = shared_context
    try:
      router_candidates = _build_business_type_candidates(conn=conn, messages=[*messages, user_msg])
      if router_candidates:
        shared_context_for_router = dict(shared_context or {})
        shared_context_for_router["business_type_candidates"] = router_candidates
    except Exception:
      shared_context_for_router = shared_context
    # Route the user's message through the GPT-only intent router first.
    confirm_override = str(
      confirm_question or _detect_confirm_question(last_assistant) or ""
    ).strip()
    if competitive_intent_override:
      action = str(competitive_intent_override.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(competitive_intent_override.get("router_msg") or "").strip())
      patch = (
        competitive_intent_override.get("patch")
        if isinstance(competitive_intent_override.get("patch"), dict)
        else None
      )
    else:
      intent = route_intent(
        consult_type="unified",
        user_message=message,
        baseline_json=baseline_json,
        shared_context=shared_context_for_router,
        recent_messages=recent_messages,
        confirm_question_override=confirm_override,
        active_focus=focus,
      )

      action = str(intent.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(intent.get("assistant_message") or "").strip())
      patch = intent.get("patch") if isinstance(intent.get("patch"), dict) else None

    milestone_patch_from_user: Optional[List[Dict[str, Any]]] = None
    if action == "edit_patch" and isinstance(patch, dict):
      patch = _normalize_unscoped_patch(patch, focus=focus)
      candidate = patch.get("milestones")
      if candidate is None:
        candidate = patch.get("ops.milestones")
      if isinstance(candidate, str):
        try:
          candidate = json.loads(candidate)
        except Exception:
          candidate = None
      if isinstance(candidate, list):
        milestone_patch_from_user = [m for m in candidate if isinstance(m, dict)]
    if not milestone_patch_from_user and pending_ops_milestone:
      try:
        extracted = _extract_ops_pending_milestone(
          text=message,
          route_intent=route_intent,
          ops_json=ops_json,
          shared_context=shared_context,
        )
        if extracted:
          milestone_patch_from_user = extracted
      except Exception:
        milestone_patch_from_user = None

    if str(focus).strip().lower() == "ops" and not _has_confirmed_milestone(ops_json):
      milestones_val: Optional[List[Dict[str, Any]]] = None
      if pending_ops_milestone and action == "confirm_proceed":
        milestones_val = list(pending_ops_milestone)
      elif milestone_patch_from_user:
        milestones_val = milestone_patch_from_user

      if milestones_val:
        if pending_ops_milestone:
          pending_item = pending_ops_milestone[0] if isinstance(pending_ops_milestone, list) else None
        else:
          pending_item = None
        if isinstance(pending_item, dict):
          for item in milestones_val:
            if not isinstance(item, dict):
              continue
            if not str(item.get("description") or "").strip():
              item["description"] = pending_item.get("description")
            if not str(item.get("timing") or "").strip():
              item["timing"] = pending_item.get("timing")
        ops_json["milestones"] = milestones_val
        _enrich_milestones_timing(ops_json, reference_date=current_date)
        shared_context["operating_model"] = ops_json
        pending_ops_milestone = []

        intake_context_followup = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        followup_turn = consultant_chat_turn(
          intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
        )
        assistant_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          operating_model_json=ops_json,
          target_market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          pending_ops_milestone_json=pending_ops_milestone,
          fulfillment_json=fulfillment_json,
          active_focus="ops",
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "ops",
            "awaiting_confirmation": False,
            "done": False,
            "action": "edit_patch",
            "assistant_message": assistant_text,
          }
        )

      if pending_ops_milestone:
        pending = pending_ops_milestone[0]
        desc = str(pending.get("description") or "").strip()
        timing = str(pending.get("timing") or "").strip()
        milestone_line = desc
        if timing:
          milestone_line = f"{desc} ({timing})"
        assistant_text = (
          f"Proposed milestone: {milestone_line}. Does this work, or what should we change?"
        )
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          pending_ops_milestone_json=pending_ops_milestone,
          active_focus="ops",
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "ops",
            "awaiting_confirmation": False,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

    # Sections can only advance after the explicit final confirmation has been proposed.
    finalize_flags = {
      "ops": ops_finalize_proposed,
      "market": market_finalize_proposed,
      "people": people_finalize_proposed,
      "financials": financials_finalize_proposed,
    }
    if action == "confirm_proceed" and focus in finalize_flags and not finalize_flags.get(focus):
      action = "continue_chat"

    # If the intake is fully complete, "continue" should guide the user to submission.
    if focus == "done" and action == "continue_chat":
      assistant_text = 'Consistency check is complete and the facts line up well enough to proceed.\n\nClick "Submit intake" to finish.'
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus="done",
        business_facts=business_facts,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "done",
          "awaiting_confirmation": False,
          "done": True,
          "action": "ready_to_submit",
          "assistant_message": assistant_text,
        }
      )

    if action == "edit_patch" and patch:
      patch = _normalize_unscoped_patch(patch, focus=focus)
      people_patch_applied = bool(
        str(focus or "").strip().lower() == "people"
        or any(str(k).strip().lower().startswith("people.") for k in patch.keys())
      )
      baseline_people_json = json.loads(json.dumps(people_json)) if people_json else {}
      business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
        patch,
        business_facts=business_facts,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        fulfillment_json=fulfillment_json,
      )
      try:
        shared_context = dict(shared_context or {})
        shared_context["operating_model"] = ops_json
        shared_context["target_market"] = market_json
        shared_context["people_capability"] = people_json
        shared_context["financials"] = financials_json
        base_year1 = assemble_financials_year1(shared_context, None)
        if _year1_drivers_conflict(financials_year1_json, base_year1):
          financials_year1_json = base_year1
        else:
          financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
        if isinstance(financials_year1_json, dict) and financials_year1_json:
          shared_context["financials_year1_json"] = financials_year1_json
        revenue_math_line = build_revenue_math_line(
          financials_year1_json,
          unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
        )
        revenue_constraints_snippet = build_revenue_constraints_snippet(
          shared_context,
          financials_year1_json,
          business_start_date=str(business_facts.get("start_date") or "").strip() or None,
        )
        guardrail_signals = build_revenue_guardrail_signals(
          shared_context,
          financials_year1_json,
          business_start_date=str(business_facts.get("start_date") or "").strip() or None,
          fulfillment_context=fulfillment_json,
        )
        driver_signature = build_revenue_driver_signature(financials_year1_json)
        guardrail_acknowledged = (
          get_acknowledged_signature(str(draft_id).strip()) == driver_signature
        )
        guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged
      except Exception:
        pass
      def _coerce_wage(value: Any) -> Optional[float]:
        try:
          return float(value)
        except Exception:
          return None

      def _people_key(item: Dict[str, Any]) -> str:
        name = str(item.get("full_name") or "").strip().lower()
        title = str(item.get("role_title") or "").strip().lower()
        if name or title:
          return f"{name}::{title}".strip(":")
        return ""

      def _role_key(item: Dict[str, Any]) -> str:
        return str(item.get("role_title") or "").strip().lower()

      def _build_wage_map(items: List[Dict[str, Any]], key_fn) -> Dict[str, Optional[float]]:
        mapping: Dict[str, Optional[float]] = {}
        for it in items:
          if not isinstance(it, dict):
            continue
          key = key_fn(it)
          if not key:
            continue
          mapping[key] = _coerce_wage(it.get("annual_wage"))
        return mapping

      def _mark_client_overrides(
        updated_items: List[Dict[str, Any]],
        baseline_map: Dict[str, Optional[float]],
        key_fn,
      ) -> None:
        for it in updated_items:
          if not isinstance(it, dict):
            continue
          key = key_fn(it)
          if not key:
            continue
          new_wage = _coerce_wage(it.get("annual_wage"))
          if new_wage is None:
            continue
          old_wage = baseline_map.get(key)
          if old_wage is None or abs(new_wage - old_wage) > 0.01:
            it["wage_source"] = "client_override"

      try:
        baseline_people_list = (
          baseline_people_json.get("people") if isinstance(baseline_people_json, dict) else []
        )
        baseline_roles_list = (
          baseline_people_json.get("inferred_roles") if isinstance(baseline_people_json, dict) else []
        )
        if isinstance(people_json, dict):
          updated_people_list = people_json.get("people")
          updated_roles_list = people_json.get("inferred_roles")
          if isinstance(updated_people_list, list) and isinstance(baseline_people_list, list):
            _mark_client_overrides(
              updated_people_list, _build_wage_map(baseline_people_list, _people_key), _people_key
            )
          if isinstance(updated_roles_list, list) and isinstance(baseline_roles_list, list):
            _mark_client_overrides(
              updated_roles_list, _build_wage_map(baseline_roles_list, _role_key), _role_key
            )
      except Exception:
        pass
      business_type_touched = False
      if isinstance(patch, dict):
        business_type_touched = "ops.business_type" in patch
      try:
        try:
          from intake_business_types import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.intake_business_types import (  # type: ignore
            get_naics_from_business_type,
          )
        if business_type_touched:
          try:
            bt_candidates = _build_business_type_candidates(conn=conn, messages=[*messages, user_msg])
          except Exception:
            bt_candidates = []
          ops_json["business_type"] = _normalize_business_type_from_candidates(
            ops_json.get("business_type"),
            bt_candidates,
          )
        if business_type_touched:
          if ops_json.get("business_type"):
            ops_json["business_naics_6"] = get_naics_from_business_type(
              conn, ops_json.get("business_type")
            )
          else:
            ops_json["business_naics_6"] = None
        elif ops_json.get("business_type") and not ops_json.get("business_naics_6"):
          try:
            bt_candidates = _build_business_type_candidates(conn=conn, messages=[*messages, user_msg])
          except Exception:
            bt_candidates = []
          ops_json["business_type"] = _normalize_business_type_from_candidates(
            ops_json.get("business_type"),
            bt_candidates,
          )
          ops_json["business_naics_6"] = get_naics_from_business_type(
            conn, ops_json.get("business_type")
          )
      except Exception:
        if business_type_touched and "business_naics_6" not in ops_json:
          ops_json["business_naics_6"] = None
      try:
        _enrich_milestones_timing(ops_json, reference_date=current_date)
      except Exception:
        pass
      try:
        from people_roles import (  # type: ignore
          apply_oews_wages,
          apply_oews_wages_to_people,
          format_roles_summary,
        )

        people_list = people_json.get("people") if isinstance(people_json, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        if people_list:
          enriched_people = apply_oews_wages_to_people(
            conn,
            people=people_list,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          people_json["people"] = enriched_people

        roles = people_json.get("inferred_roles") if isinstance(people_json, dict) else None
        roles = roles if isinstance(roles, list) else []
        if roles:
          enriched_roles = apply_oews_wages(
            conn,
            roles=roles,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          people_json["inferred_roles"] = enriched_roles
          people_json["inferred_roles_summary"] = format_roles_summary(enriched_roles)
      except Exception:
        pass
      active_focus_out = focus
      status_out: str | None = None
      consistency_passed_out = False
      completed_out = False
      confirm_question_live = _detect_confirm_question(last_assistant)

      # If the draft was already marked complete, edits must reopen it and trigger
      # a new consistency pass.
      if str(draft_status).strip().lower() == "completed" or focus == "done":
        status_out = "in_progress"
        active_focus_out = "consistency"

      # For edit patches, the intent router is used only to interpret intent and
      # produce the deterministic patch. The domain consultant generates the next
      # conversational turn. Showing both messages causes duplicated acknowledgements
      # and repeated questions.
      #
      # Exception: if the edit re-opens a completed intake into Consistency, keep the
      # router acknowledgement so the user clearly sees the update before the audit.
      assistant_text = router_msg if (confirm_question_live or active_focus_out != focus) else ""
      # If we're awaiting a section-final confirmation, re-ask the confirm question
      if confirm_question_live:
        assistant_text = f"{assistant_text}\n\n{confirm_question_live}".strip()
      else:
        # Otherwise, keep the intake moving: acknowledge the edit and then continue
        # with the next question for the current focus (no standstills).
        shared_context_live = dict(shared_context or {})
        shared_context_live["operating_model"] = ops_json
        shared_context_live["target_market"] = market_json
        shared_context_live["people_capability"] = people_json
        shared_context_live["financials"] = financials_json

        intake_context_followup = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "address_street": payload.get("address_street"),
          "address_city": payload.get("address_city"),
          "address_state": payload.get("address_state"),
          "address_zip": payload.get("address_zip"),
          "address_country": payload.get("address_country"),
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context_live,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        intake_context_followup["financials_year1_json"] = financials_year1_json
        intake_context_followup["revenue_math_line"] = revenue_math_line
        intake_context_followup["revenue_constraints_snippet"] = revenue_constraints_snippet
        intake_context_followup["revenue_driver_patch"] = revenue_driver_patch
        intake_context_followup["revenue_guardrail_triggered"] = guardrail_triggered
        intake_context_followup["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
        intake_context_followup["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

        followup_focus = active_focus_out if active_focus_out != "done" else focus
        if followup_focus == "market":
          consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
          if consumer_type not in ("consumer", "b2b", "mixed"):
            consumer_type = "consumer"
          intake_context_followup["consumer_type"] = consumer_type

        if followup_focus == "ops":
          followup_turn = consultant_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "market":
          followup_turn = target_market_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "people":
          followup_turn = people_capability_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "financials":
          followup_turn = financials_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "consistency":
          if assistant_text:
            assistant_text = f"{assistant_text}\n\nQuick check: since we changed a key fact, I'm going to re-run a brief consistency check to make sure everything still lines up.".strip()
          followup_turn = consistency_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
          if bool(followup_turn.get("finalize_ready", False)):
            consistency_passed_out = True
            completed_out = True
            active_focus_out = "done"
            status_out = "completed"
        else:
          followup_turn = {"assistant_message": ""}

        followup_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        if focus == "market":
          followup_text = _strip_acs_codes(followup_text)
        if followup_focus == "financials":
          followup_text = _append_constraints_snippet(
            followup_text,
            revenue_constraints_snippet,
            messages,
            force=True,
          )
        if followup_text:
          if assistant_text:
            assistant_text = f"{assistant_text}\n\n{followup_text}".strip()
          else:
            assistant_text = followup_text
        if consistency_passed_out:
          if 'Click "Submit intake"' not in assistant_text:
            assistant_text = f'{assistant_text}\n\nClick "Submit intake" to finish.'.strip()

      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json,
        target_market_json=market_json,
        people_json=people_json if people_patch_applied else None,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        fulfillment_json=fulfillment_json,
        active_focus=active_focus_out,
        business_facts=business_facts,
        consistency_passed=consistency_passed_out,
        status=status_out,
        completed=completed_out,
        flat_fields=_finalize_flag_field(focus, False),
      )

      action_out = "consistency_passed" if active_focus_out == "done" else "edit_patch"
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": active_focus_out,
          "awaiting_confirmation": bool(confirm_question_live),
          "done": bool(active_focus_out == "done"),
          "action": action_out,
          "assistant_message": assistant_text,
        }
      )

    if action == "confirm_proceed":
      confirmations: Dict[str, bool] = {focus: True}
      next_focus = _next_focus(focus)

      # Generate the first question for the next focus immediately.
      start_instruction = _start_instruction_for_focus(next_focus)
      turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
      intake_context_next: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "consumer_type": (ops_json or {}).get("consumer_type"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
      }
      intake_context_next["financials_year1_json"] = financials_year1_json
      intake_context_next["revenue_math_line"] = revenue_math_line
      intake_context_next["revenue_constraints_snippet"] = revenue_constraints_snippet
      intake_context_next["revenue_driver_patch"] = revenue_driver_patch
      intake_context_next["revenue_guardrail_triggered"] = guardrail_triggered
      intake_context_next["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
      intake_context_next["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

      if next_focus == "ops":
        next_assistant = consultant_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "market":
        next_assistant = target_market_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "people":
        next_assistant = people_capability_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "financials":
        next_assistant = financials_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "consistency":
        next_assistant = consistency_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "done":
        next_assistant = "Great, you're ready to submit your intake."
      else:
        next_assistant = "Continue."

      transition = ""
      if next_focus == "market":
        transition = "Great, let's move on to Target Market."
      elif next_focus == "people":
        transition = "Great, let's move on to Human Resources."
      elif next_focus == "financials":
        transition = "Great, let's move on to Financials."
      elif next_focus == "consistency":
        transition = "Great, I'm going to do a quick consistency check before submission."
      if transition:
        next_assistant = f"{transition}\n\n{next_assistant}".strip() if next_assistant else transition

      next_assistant = sanitize_fact_template(str(next_assistant or "").strip())
      if next_focus == "market":
        next_assistant = _strip_acs_codes(next_assistant)
      if next_focus == "financials":
        next_assistant = _append_constraints_snippet(
          next_assistant,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": next_assistant}],
        confirmations=confirmations,
        active_focus=next_focus,
        business_facts=business_facts,
        flat_fields=_finalize_flag_field(focus, False),
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": next_focus,
          "awaiting_confirmation": False,
          "done": bool(next_focus == "done"),
          "action": "confirm_proceed",
          "assistant_message": next_assistant,
        }
      )

    if action == "confirm_clarify":
      assistant_text = sanitize_fact_template(router_msg)
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus=focus,
        business_facts=business_facts,
        flat_fields=_finalize_flag_field(focus, False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": False,
          "action": "confirm_clarify",
          "assistant_message": assistant_text,
        }
      )

    if action == "answer_readonly":
      assistant_text = sanitize_fact_template(router_msg)
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus=focus,
        business_facts=business_facts,
        flat_fields=_finalize_flag_field(focus, False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": False,
          "action": "answer_readonly",
          "assistant_message": assistant_text,
        }
      )

    # continue_chat: run the current focus consult normally.
    intake_context = {
      "client_id": client_id,
      "draft_id": str(draft_id).strip(),
      "business_name": business_facts.get("name"),
      "business_start_date": business_facts.get("start_date"),
      "address": business_facts.get("address"),
      "address_street": payload.get("address_street"),
      "address_city": payload.get("address_city"),
      "address_state": payload.get("address_state"),
      "address_zip": payload.get("address_zip"),
      "address_country": payload.get("address_country"),
      "current_date": current_date_iso,
      "business_stage_hint": business_stage_hint,
      "shared_context": shared_context,
      "operating_model_json": ops_json,
      "target_market_json": market_json,
      "people_json": people_json,
      "financials_json": financials_json,
      "fulfillment_json": fulfillment_json,
    }
    intake_context["financials_year1_json"] = financials_year1_json
    intake_context["revenue_math_line"] = revenue_math_line
    intake_context["revenue_constraints_snippet"] = revenue_constraints_snippet
    intake_context["revenue_driver_patch"] = revenue_driver_patch
    intake_context["revenue_guardrail_triggered"] = guardrail_triggered
    intake_context["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
    intake_context["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []
    if focus == "market":
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      if consumer_type not in ("consumer", "b2b", "mixed"):
        consumer_type = "consumer"
      intake_context["consumer_type"] = consumer_type
    if focus == "ops":
      turn = consultant_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "market":
      turn = target_market_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "people":
      turn = people_capability_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "financials":
      turn = financials_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "consistency":
      turn = consistency_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    else:
      turn = {"assistant_message": "Continue.", "finalize_ready": False}

    assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
    if focus == "market":
      assistant_text = _strip_acs_codes(assistant_text)
    if focus == "financials":
      assistant_text = _append_constraints_snippet(
        assistant_text,
        revenue_constraints_snippet,
        messages,
        force=True,
      )

    finalize_ready = bool(turn.get("finalize_ready", False))
    review_ready = bool(turn.get("review_ready", False))
    if str(focus).strip().lower() == "people" and review_ready and not finalize_ready:
      finalize_ready = True
    if str(focus).strip().lower() == "financials" and guardrail_triggered:
      finalize_ready = False

    if str(focus).strip().lower() == "ops" and assistant_text:
      question_count = assistant_text.count("?")
      if question_count > 1:
        first_part = assistant_text.split("?", 1)[0].strip()
        if first_part:
          assistant_text = f"{first_part}?"
        finalize_ready = False

    if (
      str(focus).strip().lower() == "ops"
      and finalize_ready
      and not str((ops_json or {}).get("competitive_advantage") or "").strip()
    ):
      proposed_advantage = _propose_ops_competitive_advantage(
        ops_json=ops_json,
        business_facts=business_facts,
        shared_context=shared_context,
      )
      proposed_advantage = sanitize_fact_template(str(proposed_advantage or "").strip())
      if proposed_advantage:
        assistant_text = (
          f"{COMPETITIVE_ADVANTAGE_PREFIX} {proposed_advantage}\n\n"
          f"{COMPETITIVE_ADVANTAGE_QUESTION}"
        )
        finalize_ready = False

    # Safety: avoid dead-end assistant replies with no next question.
    # If GPT responded with an acknowledgement only (no question) and we're not finalizing,
    # immediately ask for the next single question so the user isn't forced to type "ok".
    if (not finalize_ready) and assistant_text and ("?" not in assistant_text):
      continue_instruction = (
        "Continue. Ask exactly ONE next question for the client to answer (do not bundle)."
      )
      followup_messages = [
        *messages,
        user_msg,
        {"role": "assistant", "content": assistant_text},
        {"role": "user", "content": continue_instruction},
      ]
      try:
        if focus == "ops":
          followup_turn = consultant_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "market":
          followup_turn = target_market_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "people":
          followup_turn = people_capability_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "financials":
          followup_turn = financials_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "consistency":
          followup_turn = consistency_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        else:
          followup_turn = {"assistant_message": ""}
        followup_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        if focus == "market":
          followup_text = _strip_acs_codes(followup_text)
        if focus == "financials":
          followup_text = _append_constraints_snippet(
            followup_text,
            revenue_constraints_snippet,
            messages,
            force=True,
          )
        if followup_text:
          assistant_text = f"{assistant_text}\n\n{followup_text}".strip()
      except Exception:
        # Best-effort; if follow-up fails, keep the original reply.
        pass

    if focus == "consistency" and finalize_ready:
      assistant_text = f'{assistant_text}\n\nClick "Submit intake" to finish.'.strip()
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus="done",
        business_facts=business_facts,
        consistency_passed=True,
        status="completed",
        completed=True,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "done",
          "awaiting_confirmation": False,
          "done": True,
          "action": "consistency_passed",
          "assistant_message": assistant_text,
        }
      )
    if not finalize_ready:
      review_people = None
      if str(focus).strip().lower() == "people" and review_ready:
        review_people = people_capability_finalize(
          intake_context=intake_context,
          conversation_messages=[*messages, user_msg, {"role": "assistant", "content": assistant_text}],
        )
        for k, v in list(review_people.items() if isinstance(review_people, dict) else []):
          if isinstance(v, str):
            review_people[k] = sanitize_fact_template(v)
        try:
          from people_roles import (  # type: ignore
            apply_oews_wages,
            apply_oews_wages_to_people,
            format_roles_summary,
          )

          roles = review_people.get("inferred_roles") if isinstance(review_people, dict) else None
          roles = roles if isinstance(roles, list) else []
          people = review_people.get("people") if isinstance(review_people, dict) else None
          people = people if isinstance(people, list) else []
          enriched_people = apply_oews_wages_to_people(
            conn,
            people=people,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          enriched_roles = apply_oews_wages(
            conn,
            roles=roles,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          review_people["business_naics_6"] = ops_json.get("business_naics_6")
          review_people["people"] = enriched_people
          review_people["inferred_roles"] = enriched_roles
          review_people["inferred_roles_summary"] = format_roles_summary(enriched_roles)
        except Exception:
          if isinstance(review_people, dict):
            if "inferred_roles" not in review_people:
              review_people["inferred_roles"] = []
            if "inferred_roles_summary" not in review_people:
              review_people["inferred_roles_summary"] = ""
            if "business_naics_6" not in review_people:
              review_people["business_naics_6"] = None
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        active_focus=focus,
        business_facts=business_facts,
        financials_year1_json=financials_year1_json if focus == "financials" else None,
        pending_ops_milestone_json=pending_ops_milestone if focus == "ops" else None,
        flat_fields=_finalize_flag_field(focus, False),
        people_json=review_people if review_ready else None,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    # Finalize the current focus into structured JSON, then ask for confirmation.
    final_messages = [*messages, user_msg, {"role": "assistant", "content": assistant_text}]

    if focus == "ops":
      business_type_candidates = _build_business_type_candidates(conn=conn, messages=final_messages)
      intake_context["business_type_candidates"] = business_type_candidates
      final_obj = consultant_finalize(intake_context=intake_context, conversation_messages=final_messages)
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      existing_advantage = str((ops_json or {}).get("competitive_advantage") or "").strip()
      if (
        existing_advantage
        and isinstance(final_obj, dict)
        and not str(final_obj.get("competitive_advantage") or "").strip()
      ):
        final_obj["competitive_advantage"] = existing_advantage
      if isinstance(final_obj, dict):
        lob_models = final_obj.get("lob_models")
        if isinstance(lob_models, list) and len(lob_models) == 1:
          products = lob_models[0].get("products") if isinstance(lob_models[0], dict) else None
          if isinstance(products, list) and len(products) == 1 and isinstance(products[0], dict):
            product = products[0]

            def _is_missing_number(value: Any) -> bool:
              if value is None:
                return True
              if isinstance(value, bool):
                return True
              try:
                return float(value) <= 0
              except Exception:
                return True

            def _maybe_set_text(field: str) -> None:
              if not final_obj.get(field) and product.get(field) is not None:
                final_obj[field] = product.get(field)

            def _maybe_set_number(field: str) -> None:
              if _is_missing_number(final_obj.get(field)) and product.get(field) is not None:
                final_obj[field] = product.get(field)

            _maybe_set_text("unit_name")
            _maybe_set_text("unit_description")
            _maybe_set_text("unit_cadence")
            _maybe_set_number("unit_price")
            _maybe_set_number("units_per_week_capacity")
            _maybe_set_number("units_per_period_capacity")
      try:
        try:
          from intake_business_types import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.intake_business_types import (  # type: ignore
            get_naics_from_business_type,
          )

        if final_obj.get("business_type"):
          final_obj["business_naics_6"] = get_naics_from_business_type(
            conn, final_obj.get("business_type")
          )
      except Exception:
        if "business_naics_6" not in final_obj:
          final_obj["business_naics_6"] = None
      try:
        _enrich_milestones_timing(final_obj, reference_date=current_date)
      except Exception:
        pass
      summary_text = str(final_obj.get("business_description_summary") or "").strip() or "Operational intake complete."
      if isinstance(final_obj, dict):
        final_obj.pop("business_description_summary", None)
      assistant_final = f"{summary_text}\n\n{OPS_CONFIRM_QUESTION}".strip()
      ops_json = final_obj
      market_json_out = None
      people_json_out = None
      financials_json_out = None
    elif focus == "market":
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      mapping_rows: List[Dict[str, Any]] = []
      if consumer_type != "b2b":
        mapping_rows = _fetch_target_market_mapping_rows(conn)
      final_obj = target_market_finalize(
        intake_context={**intake_context, "consumer_type": consumer_type},
        conversation_messages=final_messages,
        mapping_rows=mapping_rows,
      )
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      summary_text = str(final_obj.get("target_market_summary") or "").strip() or "Target market intake complete."
      if isinstance(final_obj, dict):
        final_obj.pop("target_market_summary", None)
      assistant_final = f"{summary_text}\n\n{MARKET_CONFIRM_QUESTION}".strip()
      assistant_final = _strip_acs_codes(assistant_final)
      market_json = final_obj
      market_json_out = final_obj
      people_json_out = None
      financials_json_out = None
      ops_json_out = None
    elif focus == "people":
      final_obj = people_capability_finalize(intake_context=intake_context, conversation_messages=final_messages)
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      try:
        from people_roles import (  # type: ignore
          apply_oews_wages,
          apply_oews_wages_to_people,
          format_roles_summary,
        )

        roles = final_obj.get("inferred_roles") if isinstance(final_obj, dict) else None
        roles = roles if isinstance(roles, list) else []
        people_list = final_obj.get("people") if isinstance(final_obj, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        enriched_people = apply_oews_wages_to_people(
          conn,
          people=people_list,
          business_type=ops_json.get("business_type"),
          business_stage=ops_json.get("business_stage"),
          address_state=business_facts.get("address_state"),
          address=business_facts.get("address"),
          business_naics_6=ops_json.get("business_naics_6"),
        )
        enriched_roles = apply_oews_wages(
          conn,
          roles=roles,
          business_type=ops_json.get("business_type"),
          business_stage=ops_json.get("business_stage"),
          address_state=business_facts.get("address_state"),
          address=business_facts.get("address"),
          business_naics_6=ops_json.get("business_naics_6"),
        )
        final_obj["business_naics_6"] = ops_json.get("business_naics_6")
        final_obj["people"] = enriched_people
        final_obj["inferred_roles"] = enriched_roles
        final_obj["inferred_roles_summary"] = format_roles_summary(enriched_roles)
      except Exception:
        if "inferred_roles" not in final_obj:
          final_obj["inferred_roles"] = []
        if "inferred_roles_summary" not in final_obj:
          final_obj["inferred_roles_summary"] = ""
        if "business_naics_6" not in final_obj:
          final_obj["business_naics_6"] = None
      summary_text = str(final_obj.get("key_people_summary") or "").strip() or "People & capability intake complete."
      if isinstance(final_obj, dict):
        final_obj.pop("key_people_summary", None)
      roles_summary = str(final_obj.get("inferred_roles_summary") or "").strip()
      if roles_summary:
        summary_text = f"{summary_text}\n\n{roles_summary}".strip()
      assistant_final = f"{summary_text}\n\n{PEOPLE_CONFIRM_QUESTION}".strip()
      people_json = final_obj
      people_json_out = final_obj
      market_json_out = None
      financials_json_out = None
      ops_json_out = None
    elif focus == "financials":
      final_obj = financials_finalize(intake_context=intake_context, conversation_messages=final_messages)
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      summary_text = str(final_obj.get("financials_summary") or "").strip() or "Financials intake complete."
      if isinstance(final_obj, dict):
        final_obj.pop("financials_summary", None)
      assistant_final = f"{summary_text}\n\n{FIN_CONFIRM_QUESTION}".strip()
      financials_json = final_obj
      financials_json_out = final_obj
      market_json_out = None
      people_json_out = None
      ops_json_out = None
    else:
      assistant_final = assistant_text
      ops_json_out = None
      market_json_out = None
      people_json_out = None
      financials_json_out = None

    assistant_final = sanitize_fact_template(str(assistant_final or "").strip())

    assistant_payload: Dict[str, Any] = {"role": "assistant", "content": assistant_final}

    append_messages(
      conn,
      draft_id=str(draft_id).strip(),
      new_messages=[user_msg, assistant_payload],
      operating_model_json=ops_json if focus == "ops" else None,
      target_market_json=market_json if focus == "market" else None,
      people_json=people_json if focus == "people" else None,
      financials_json=financials_json if focus == "financials" else None,
      financials_year1_json=financials_year1_json if focus == "financials" else None,
      active_focus=focus,
      business_facts=business_facts,
      consistency_passed=False,
      flat_fields=_finalize_flag_field(focus, True),
    )

    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "client_id": client_id,
        "active_focus": focus,
        "awaiting_confirmation": True,
        "done": False,
        "action": "await_confirmation",
        "assistant_message": assistant_final,
      }
    )
  except Exception as exc:
    app.logger.exception("Failed intake consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
  finally:
    try:
      conn.close()
    except Exception:
      pass
