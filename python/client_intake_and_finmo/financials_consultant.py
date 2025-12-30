from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
FINALIZE_TOKEN = "[[FINALIZE_READY]]"


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


def _final_schema() -> Dict[str, Any]:
  def _num_or_null() -> Dict[str, Any]:
    return {"type": ["number", "null"]}

  return {
    "name": "intake_financials_final",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "financials_summary": {"type": "string"},
        "current_revenue": {"type": "number"},
        "current_cogs": _num_or_null(),
        "expected_revenue_growth_pct_next_year": _num_or_null(),
        "tax_rate": _num_or_null(),
        "marketing_expense": _num_or_null(),
        "r_and_d_expense": _num_or_null(),
        "sga_expense": _num_or_null(),
        "other_operating_expense": _num_or_null(),
        "monthly_rent_expense": _num_or_null(),
        "other_monthly_debt_payments": _num_or_null(),
        "current_payroll": _num_or_null(),
        "current_num_employees": _num_or_null(),
        "planned_num_employees_5yrs": _num_or_null(),
        "current_capex": _num_or_null(),
        "planned_capex_5yr": _num_or_null(),
        "ar_balance": _num_or_null(),
        "ap_balance": _num_or_null(),
        "inventory_balance": _num_or_null(),
        "total_debt_outstanding": _num_or_null(),
        "annual_interest_payment": _num_or_null(),
        "annual_principal_payment": _num_or_null(),
        "owner_compensation": _num_or_null(),
        "cash_on_hand": _num_or_null(),
        "confidence": {"type": "number"},
      },
      "required": [
        "financials_summary",
        "current_revenue",
        "current_cogs",
        "expected_revenue_growth_pct_next_year",
        "tax_rate",
        "marketing_expense",
        "r_and_d_expense",
        "sga_expense",
        "other_operating_expense",
        "monthly_rent_expense",
        "other_monthly_debt_payments",
        "current_payroll",
        "current_num_employees",
        "planned_num_employees_5yrs",
        "current_capex",
        "planned_capex_5yr",
        "ar_balance",
        "ap_balance",
        "inventory_balance",
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

  system = f"""
You are a business consultant running the Financials intake conversation.

Goal:
- Capture the client's baseline financial inputs required for their financial model.
- Ask one question at a time and keep it non-overwhelming.
- Do not invent values. If the client is unsure, ask for their best estimate and confirm.

Data to capture (you can gather over multiple turns):
- current_revenue (annual, numeric; allow 0 for pre-revenue)
- current_cogs (annual, numeric; required if revenue > 0)
- expected_revenue_growth_pct_next_year (percent, numeric; required if revenue > 0; example: 10 means 10%)
- tax_rate (percent, numeric; example: 25 means 25%)
- operating expenses: marketing_expense, r_and_d_expense, sga_expense, other_operating_expense (annual)
- monthly_rent_expense (monthly)
- other_monthly_debt_payments (monthly)
- current_payroll (annual)
- current_num_employees (count)
- planned_num_employees_5yrs (count)
- current_capex (annual)
- planned_capex_5yr (annual)
- working capital: ar_balance, ap_balance, inventory_balance (current balances)
- debt/liquidity: total_debt_outstanding, annual_interest_payment, annual_principal_payment, owner_compensation, cash_on_hand (annual or current as applicable)

Style:
- Use simple language and confirm units (annual vs monthly) in the question.
- Keep answers numeric. If they give ranges, ask for one number.
- Do not discuss operations, target market, or people except as context to clarify financial scope.

Output rules:
- Respond with normal conversation text (NOT JSON).
- When you are confident all required fields are complete, append the token
  {FINALIZE_TOKEN} on its own line at the very end of your message.
""".strip()

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
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")

  text = _parse_responses_text(resp.json())
  finalize_ready = FINALIZE_TOKEN in text
  text = text.replace(FINALIZE_TOKEN, "").strip()
  return {"assistant_message": text, "finalize_ready": finalize_ready}


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
- Do not invent values. Use only values the client provided and explicitly agreed to.
- Values must be numeric. Percent fields (tax_rate, expected_revenue_growth_pct_next_year) must be given as percent numbers (e.g., 10 means 10%).
- If current_revenue > 0, current_cogs and expected_revenue_growth_pct_next_year must not be null.
- If a field was not discussed and the client did not provide a value, return null for that field (except required-by-revenue rule above).
- financials_summary should be a short, human-readable recap of the key financial assumptions (1 paragraph).
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
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")

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

