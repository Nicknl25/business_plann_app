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
- Capture the client's best-current picture of their financial reality as of last month.
- Ask one question at a time and keep it non-overwhelming.
- Behave like a human consultant: infer intent, keep it conversational, and avoid rigid command-style prompts.

Core rule for this section:
- Do not ask the client to choose or label a time basis. Use the anchor "as of last month".
- Anchor everything to "as of last month". If the client doesn't have the item, explicitly tell them you're recording 0 and move on.
- Nothing should be left unknown: if you can't get a clear answer after minimal clarification, record 0 and move on.

Style:
- One plain question sentence per message.
- Optional short bullet choices under it (not numbered).
- Explain each item in everyday terms (assume no finance background).
- Only ask for a number if the client actually has the item as of last month.
- If the client says "no", "none", "not yet", or they don't know after brief clarification, record 0 and explicitly say so.
- If they give a range, ask for one best number. If they give formatted strings ($, commas, "k"), interpret them into a number.
- Ask the minimum number of clarifying questions needed to reconcile economic reality, then stop. Usually 0–1; occasionally 2; never a chain.
- Use information from other consults only to reconcile reality (not to debate or forecast).

Items to cover (one at a time, in a sensible order):
- Money coming in (revenue)
- Direct costs to deliver product/service (COGS)
- Other regular operating bills (other operating expense)
- Rent payments (rent)
- Payroll for employees (payroll) and headcount (employees)
- Owner pay or owner's draws (owner compensation)
- Larger one-time equipment/investment spend (capex)
- Debt (how much is owed) and required payments; if there is no debt, do not ask about interest or principal and record them as 0
- Cash on hand (cash)
- Money customers owe you (AR), money you owe others (AP), and inventory on hand (inventory)

Everyday phrasing guide (adapt as needed; keep it short and natural):
- Revenue: "money that came in from customers"
- COGS: "what it cost to make/buy what you sold, or to deliver the service"
- Other operating expense: "other regular business bills (utilities, software, insurance, shipping, etc.)"
- Rent: "rent for your space"
- Payroll: "what you paid employees"
- Employees: "how many people were on payroll"
- Owner compensation: "money you paid yourself from the business (wages/draws)"
- Capex: "bigger one-time purchases like equipment, vehicles, or build-out"
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
- Do not invent non-zero values. Use only values the client provided; if a value is unknown/not applicable, return 0.
- No nulls: every numeric field must be a number (0 is allowed).
- All values must be >= 0.
- If total_debt_outstanding is 0, annual_interest_payment and annual_principal_payment must be 0.

Unit conventions (do not mention these in the summary):
- Treat these as annualized flow assumptions: current_revenue, current_cogs, other_operating_expense, current_payroll, current_capex, annual_interest_payment, annual_principal_payment, owner_compensation.
  - If the conversation only establishes a "last month" amount, annualize it by multiplying by 12.
  - If the client clearly stated a yearly total, use it as-is.
- Treat these as last-month amounts: monthly_rent_expense, other_monthly_debt_payments.
- Treat these as end-of-last-month balances: ar_balance, ap_balance, inventory_balance, total_debt_outstanding, cash_on_hand.
- current_num_employees is a count; round to a whole number if needed.

financials_summary should be a short, plain-language recap anchored to "as of last month" (1 paragraph).
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
