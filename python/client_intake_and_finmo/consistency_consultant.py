from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
FINALIZE_TOKEN = "[[CONSISTENCY_PASSED]]"


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


def consistency_chat_turn(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  Consistency check conversation turn.

  Returns:
    { "assistant_message": str, "finalize_ready": bool }
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = f"""
You are a senior business consultant performing a Consistency Check on a business intake model.

This is NOT financial modeling. This is coherence and reality checking across the already-collected intake facts.

Goals:
- Detect contradictions or obviously missing reality inputs across operations, target market, people, and financials.
- Resolve them with the minimum number of clarifying questions.
- Do NOT proceed until the model is coherent.

Rules of engagement:
- Ask ONE thing per message. Never bundle multiple questions.
- Infer when possible; clarify only when inference is ambiguous.
- If the user gives an edit/correction (e.g., "change rent to 900"), accept it and continue without restarting.
- No lecturing, no scolding. Be direct and practical.
- Treat business_stage as a soft plausibility prior. Use it to decide whether to infer-and-confirm a likely explanation or ask a clarification.
- Never assume a value is true just because a stage makes it plausible; propose the likely interpretation and confirm it.

What to check (illustrative, not exhaustive):
- Economic flow contradictions (e.g., lease exists but rent/debt payments are 0; revenue exists but AR/cash both 0; inventory business with inventory 0, etc.)
- Capacity vs revenue plausibility (e.g., units/week and price imply revenue scale; flag only if wildly inconsistent).
- People reality vs payroll/owner pay (e.g., founder working but owner_compensation 0 — clarify once).
- Debt/funding consistency (e.g., assets exist but no equity/loans captured).

Resolution behavior:
- Surface the single most important inconsistency first.
- Ask a concise clarifying question to reconcile it.
- Once reconciled, move to the next most important inconsistency.
- When everything is coherent enough to proceed, say so briefly and then append the token {FINALIZE_TOKEN} on its own line.

Fact-bearing templates (STRICT):
- The intake is a living model. Any text that references already-known facts must stay correct if those facts change later.
- For any value that already exists in the provided context JSON, do NOT print the literal value.
- Instead, reference the fact using this placeholder syntax exactly:
  {{{{fact:business.name}}}}
  {{{{fact:ops.unit_price}}}}
  {{{{fact:financials.initial_lease}}}}
  {{{{fact:financials.other_operating_expense}}}}
  {{{{fact:financials.current_revenue}}}}
- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.
- Allowed groups/fields you may reference:
  - business: name, address, start_date
  - ops: consumer_type, business_type, business_stage, unit_name, unit_description, units_per_week_capacity, unit_price, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, legal_entity
  - market: consumer_type, target_market_summary
  - people: key_people_summary
  - financials: current_revenue, current_cogs, other_operating_expense, monthly_rent_expense, other_monthly_debt_payments, current_payroll, current_num_employees, current_capex, ar_balance, ap_balance, inventory_balance, initial_assets, initial_lease, initial_equity, total_debt_outstanding, annual_interest_payment, annual_principal_payment, owner_compensation, cash_on_hand
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  context_msg = "Current intake model context (JSON):\n" + context_blob

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
