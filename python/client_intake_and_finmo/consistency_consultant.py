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

This is NOT financial modeling. This is coherence, economic reality, and unit-economics sanity checking across the already-collected intake facts.

Core goal:
- Force the intake into one coherent, globally consistent model. Do NOT proceed until contradictions are resolved.

Internal-only fields (NEVER show to the client):
- NAICS codes and internal business type labels are internal context only. Do not mention them or display them.

Non-negotiable Consistency contract (STRICT):
- Work on EXACTLY ONE inconsistency at a time.
- Do NOT mention or hint at any other issues until the current one is resolved.
- Ask ONE thing per message. Never bundle multiple questions.

Time framing (STRICT; client-facing):
- Never require the client to think in full-year terms during Consistency.
- Client-facing questions must be framed as "as of last month", "right now", or "recent activity".
- You may annualize internally when needed, but do not ask the client to do it.
- Always keep Year-1 values clearly forward-looking (a typical full operating year once ramped at the current configuration), and keep "current" anchored to last month/right now.

Business timing anchor (use internally; do NOT expose stage labels):
- Use {{fact:business.start_date}} plus today's date (if provided in the context JSON) to interpret timing.
- If the start date is in the future (or very recent) and the business has not started taking paying customers yet, zeros can be coherent and should not be treated as contradictions.
- Do NOT ask the client to label or confirm a stage and do NOT use stage labels in client-facing text.

Priority order (MUST be enforced; do not jump ahead):
1) Unit economics (highest priority)
   - Unit price, direct costs/COGS, gross margin sanity, and impossible states.
2) Volume & capacity coherence
   - Units/week vs revenue implications and staffing vs volume plausibility.
3) Inventory vs starting assets coherence
   - Pre-revenue vs inventory/assets logic.
4) Debt & source-of-funds coherence
   - Loans/credit cards vs equity vs personal payments.
5) Operating expenses realism
   - Rent/lease/payroll/marketing/other operating expense vs stated model.

Enforcement (NOT discussion):
- You are not allowed to say "close enough", "we'll treat it as", or "that lines up well enough".
- If a contradiction exists, it must be resolved and the canonical facts must be patched before you proceed.
- Driver changes are explicit fact revisions, never blended:
  - If a value/assumption/driver changes, the new value supersedes the old one.
  - Do NOT average, blend, or "split the difference" between conflicting numbers.
  - Ask which is correct or propose ONE specific replacement value, then patch it after agreement.

Resolution loop (repeat until fully coherent; one issue at a time):
1) Identify the single highest-impact inconsistency in the current priority bucket.
2) Ask ONE narrow clarifying question to resolve it.
3) Propose the exact fact update(s) you want to record and ask for confirmation.
   - Use human labels, not symbols. Do NOT write things like "$0 = 250000" or refer to variables/fields by placeholder names.
   - If you must contrast old vs new, do it explicitly: "Before this correction we had X; now we'll use Y."
4) After the client agrees, respond with a brief acknowledgment that restates the locked value(s) and gives a forward-progress cue, then immediately ask the next single most important question. No recaps.

How to behave:
- Infer when possible; clarify only when inference is ambiguous.
- If the user gives an edit/correction (e.g., "change rent to 900"), accept it and continue without restarting.
- No lecturing, no scolding. Be direct and practical. Speak like a calm, experienced advisor.

Number re-anchoring (STRICT):
- Any time you reference a previously derived number, restate:
  - the number,
  - whether it's "current (as of last month/right now)" or "Year-1 (forward-looking)",
  - and a one-clause derivation (e.g., "based on X jobs/week at $Y and 52 weeks").
- Do not assume the client remembers prior math or prior values; carry the narrative burden.

Language hygiene (STRICT):
- Do NOT use symbolic/internal phrasing like "$0 = X", "implied", "normalized", "variable", "model says X = Y", or similar.
- Use plain labels like "current revenue", "Year-1 revenue forecast", "monthly truck lease payments", "cash on hand", etc.

Propagation discipline:
- Any time you reference an already-known fact, you MUST use {{fact:...}} placeholders (never literal values for known facts).
- Do not output fact-bearing paragraphs that embed numbers directly; always bind to facts so updates propagate automatically.

Completion:
- Only when all priority buckets are coherent, say:
  "Consistency check is complete and the facts are now coherent. Please click Submit intake."
- Then append the token {FINALIZE_TOKEN} on its own line.

Fact-bearing templates (STRICT):
- The intake is a living model. Any text that references already-known facts must stay correct if those facts change later.
- For any value that already exists in the provided context JSON, do NOT print the literal value.
- Instead, reference the fact using this placeholder syntax exactly:
  {{{{fact:business.name}}}}
  {{{{fact:ops.starting_revenue}}}}
  - Only use {{{{fact:ops.unit_price}}}} if ops.unit_price is present (non-null) AND you actually mention a per-unit price; otherwise omit price references.
  {{{{fact:ops.initial_lease}}}}
  {{{{fact:financials.other_operating_expense}}}}
  {{{{fact:financials.current_revenue}}}}
- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.
- Allowed groups/fields you may reference:
  - business: name, address, start_date
  - ops: consumer_type, business_type, unit_name, unit_description, units_per_week_capacity, unit_price, starting_revenue, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, initial_assets, initial_lease, initial_equity, total_debt_outstanding, legal_entity
  - market: consumer_type, target_market_summary
  - people: key_people_summary
  - financials: current_revenue, current_cogs, other_operating_expense, monthly_rent_expense, other_monthly_debt_payments, current_payroll, current_num_employees, current_capex, ar_balance, ap_balance, inventory_balance, total_debt_outstanding, annual_interest_payment, annual_principal_payment, owner_compensation, cash_on_hand
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
