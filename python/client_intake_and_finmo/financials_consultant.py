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
) -> bool:
  lowered = text.lower()
  has_assertion = ("assumes" in lowered) and any(
    token in lowered
    for token in (
      "concurrent",
      "active",
      "capacity",
      "utilization",
      "fully booked",
      "full capacity",
    )
  )
  has_implication = any(
    token in lowered
    for token in (
      "implies",
      "means",
      "requires",
      "must",
      "would need",
    )
  )
  has_judgment = any(token in lowered for token in ("aggressive", "conservative", "balanced"))
  has_strain = any(token in lowered for token in ("strain", "tight", "pressure", "risk", "little room", "no room"))
  if guardrail_triggered and not has_strain:
    return False
  if not has_assertion or not has_implication or not has_judgment:
    return False
  return True


def _needs_revenue_rewrite(
  *,
  text: str,
  intake_context: Dict[str, Any],
) -> bool:
  if "Year 1 revenue" not in text:
    return False
  question_count = text.count("?")
  if question_count != 1:
    return True
  financials_year1_json = intake_context.get("financials_year1_json")
  if not isinstance(financials_year1_json, dict):
    financials_year1_json = {}
  cadences = _extract_cadences(financials_year1_json)
  if _is_time_slice_forbidden(text, cadences):
    return True
  guardrail_triggered = bool(intake_context.get("revenue_guardrail_triggered"))
  if not _has_required_revenue_elements(text=text, guardrail_triggered=guardrail_triggered):
    return True
  return False


def _rewrite_financials_revenue_response(
  *,
  draft_text: str,
  intake_context: Dict[str, Any],
) -> str:
  if "Year 1 revenue" not in draft_text:
    return draft_text
  if not _needs_revenue_rewrite(text=draft_text, intake_context=intake_context):
    return draft_text

  api_key = _require_openai_key()
  model = _openai_model()

  system = """
You are a compliance editor for a Financials revenue response.

Rules:
- Capacity-first framing only; do not rely on time-slice math or "12 months/periods" unless unit_cadence is monthly.
- Take a position (adjudicator), state implications plainly, and avoid hedging phrases.
- Use the required response pattern:
  1) Assertion ("This revenue setup assumes...") stating concurrency/utilization/workload.
  2) Implication: what must be true operationally.
  3) Judgment: aggressive/conservative/balanced.
  4) Risk acknowledgement if present.
  5) Single confirmation/adjustment question (one sentence, no list).
- The final response MUST include an explicit operational reality statement, an explicit judgment word, and an explicit strain statement when strain is present.
- Do not introduce new facts, benchmarks, or external data.
- Keep any required "Year 1 revenue" and constraints content intact.

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
    + "STRICT MODE: You MUST include the exact words aggressive/conservative/balanced "
    + "and an explicit strain statement when strain is present."
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

  system = f"""
You are a business consultant running the Financials intake conversation.

Goal:
- Capture the client's best-current picture of their financial reality as of last month.
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
- You will also be given revenue_constraints_snippet (deterministic).
- Start this section by presenting "Year 1 revenue:" and include the revenue_math_line verbatim.
- Immediately after the revenue_math_line, include the revenue_constraints_snippet verbatim (it is the required constraints bullet list).
- Revenue is derived at the product level; LOB totals are rollups only.
- Explain the result in plain English using narrative-only inputs (unit_name, unit_description, unit_cadence, capacity_driver, sales_modality, fulfillment_model, geographic_scope, geographic_coverage, start_date, milestones, primary_growth_lever).
- Do NOT ask "What is your revenue?" and do NOT ask for a revenue number.
- If revenue_driver_patch is present in context, acknowledge the change and re-state the updated revenue_math_line before moving on.

Financials adjudication (MANDATORY):
- You are an arbitrator, not an interviewer. Take a position, state implications plainly, then ask for agreement or correction.
- Do not use hedging phrases like "Does this feel right?", "If you'd like, we can...", or "Just to check...".
- Do not hint at a problem without stating it directly.
- Do not use "12 months", "12 periods", or similar time-slice framing unless unit_cadence is explicitly monthly (subscription-based).
- Revenue explanation must be capacity-first: emphasize concurrent workload, implied utilization, and the constrained resource (labor/system/demand).

Required response pattern (every revenue setup):
1) Assertion: "This revenue setup assumes ..." and state concurrency/utilization and implied workload.
2) Implication: explain what must be true operationally for this to hold.
3) Judgment: call it aggressive, conservative, or balanced.
4) Risk acknowledgement (if present): explicitly name the strain (capacity, ramp, timing, labor).
5) Single confirmation/adjustment question: one sentence, no list.

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

Items to cover (one at a time, in a sensible order):
- Direct costs to deliver product/service (COGS)
- Other regular operating bills (other operating expense)
- Rent payments (rent)
- Payroll for employees (payroll) and headcount (employees)
- Owner pay or owner's draws (owner compensation)
- Larger one-time equipment/investment spend (capex)
- Assets the business already uses to operate (rough total value as of last month)
- Leased/rented equipment payments (if any)
- Money/value already put into the business so far (owner/investor funding to date)
- Debt (how much is owed) and required payments; if there is no debt, do not ask about interest or principal and record them as 0
- Cash on hand (cash)
- Money customers owe you (AR), money you owe others (AP), and inventory on hand (inventory)

Everyday phrasing guide (adapt as needed; keep it short and natural):
- COGS: "what it cost to make/buy what you sold, or to deliver the service"
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
  - ops: consumer_type, business_type, unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, unit_price, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, legal_entity
  - market: consumer_type, target_market_summary
  - people: key_people_summary
  - financials: current_revenue, current_cogs, other_operating_expense, monthly_rent_expense, other_monthly_debt_payments, current_payroll, current_num_employees, current_capex, ar_balance, ap_balance, inventory_balance, initial_assets, initial_lease, initial_equity, total_debt_outstanding, annual_interest_payment, annual_principal_payment, owner_compensation, cash_on_hand

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
    raise RuntimeError(_format_openai_error(resp))

  text = _parse_responses_text(resp.json())
  finalize_ready = FINALIZE_TOKEN in text
  text = text.replace(FINALIZE_TOKEN, "").strip()
  text = _rewrite_financials_revenue_response(draft_text=text, intake_context=intake_context)
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
  - If the conversation only establishes a "last month" amount, annualize it by multiplying by 12.
  - If the client clearly stated a yearly total, use it as-is.
- Treat these as last-month amounts: monthly_rent_expense, other_monthly_debt_payments.
- Treat these as end-of-last-month balances: ar_balance, ap_balance, inventory_balance, total_debt_outstanding, cash_on_hand, initial_assets, initial_equity.
- current_num_employees is a count; round to a whole number if needed.

financials_summary should be a short, plain-language recap anchored to "as of last month" (1 paragraph).
- IMPORTANT: financials_summary is a fact-bearing template. Do NOT print literal numbers for known fields; use {{fact:financials.<field>}} (and {{fact:business.name}} if you mention the business) so the UI always renders the latest facts.
- Include the key numeric facts using placeholders so nothing renders blank, even when values are 0:
  - revenue, cogs, other operating expense, rent, payroll and headcount, owner compensation
  - cash on hand, AR, AP, inventory
  - operating assets, lease commitments, owner/investor funding to date
  - total debt outstanding and monthly debt payments (and interest/principal if applicable)
  - Use {{fact:financials.initial_assets}}, {{fact:financials.initial_lease}}, and {{fact:financials.initial_equity}} when describing assets/leases/funding.
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

