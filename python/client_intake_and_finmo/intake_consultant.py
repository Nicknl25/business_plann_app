from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

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


def _final_schema() -> Dict[str, Any]:
  return {
    "name": "intake_operating_model_final",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "consumer_type": {
          "type": "string",
          "enum": ["consumer", "b2b", "mixed"],
        },
        "business_type": {"type": "string"},
        "business_description_summary": {"type": "string"},
        "unit_name": {"type": "string"},
        "unit_description": {"type": "string"},
        "units_per_week_capacity": {"type": "number"},
        "unit_price": {"type": "number"},
        "shipping_method": {"type": "string"},
        "sales_modality": {"type": "string", "enum": ["physical", "online", "hybrid"]},
        "geographic_scope": {
          "type": "string",
          "enum": ["local", "regional", "national", "international"],
        },
        "geographic_coverage": {"type": "string"},
        "countries": {"type": "array", "items": {"type": "string"}},
        "milestones": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "description": {"type": "string"},
              "timing": {"type": "string"},
            },
            "required": ["description", "timing"],
          },
        },
        "capacity_driver": {"type": "string", "enum": ["labor", "system", "demand"]},
        "primary_growth_lever": {"type": "string"},
        "initial_assets": {"type": "number"},
        "initial_lease": {"type": "string"},
        "initial_equity": {"type": "number"},
        "total_debt_outstanding": {"type": "number"},
        "legal_entity": {"type": "string"},
        "confidence": {"type": "number"},
      },
      "required": [
        "consumer_type",
        "business_type",
        "business_description_summary",
        "unit_name",
        "unit_description",
        "units_per_week_capacity",
        "unit_price",
        "shipping_method",
        "sales_modality",
        "geographic_scope",
        "geographic_coverage",
        "countries",
        "milestones",
        "capacity_driver",
        "primary_growth_lever",
        "initial_assets",
        "initial_lease",
        "initial_equity",
        "total_debt_outstanding",
        "legal_entity",
        "confidence",
      ],
    },
  }


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


def consultant_chat_turn(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: list[Dict[str, str]],
) -> Dict[str, Any]:
  """
  Free-text consultant conversation turn (NO schema enforcement).

  Returns:
    { "assistant_message": str, "finalize_ready": bool }
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = f"""
You are a business consultant running an operational intake conversation.

Goal: infer how the business works operationally and capture a single, agreed unit price.
Early in the conversation, determine whether the business primarily sells to consumers, businesses, or both (consumer | b2b | mixed).

Forbidden topics (DO NOT ask about these): total revenue, employees, payroll, funding, marketing copy, or writing business-plan prose.

You must dynamically ask follow-ups, probe ambiguity, and reflect your understanding.
You must decide when you have enough info.
The context JSON may include shared_context with outputs from other consults; treat it as read-only facts and do not re-run other consults.

Business type classification (FIRST, REQUIRED):
- Before asking any other operational questions, classify the business type using a short professional clarification exchange.
- Ask the client to describe what the business does in plain language.
- Then produce a comprehensive 2-3 sentence operational restatement (what it is, how value is delivered, how revenue is generated at a high level, and what it is not) and ask for confirmation.
- If the client corrects you or if the description is ambiguous, ask ONE clarifying question, then restate again and confirm.
- Do not proceed to the rest of the operational intake until the client confirms the restatement.
- Do NOT show the internal business type label or any dropdown/list. This is internal classification only.

Information you must collect before finalizing (do NOT show these as internal field names to the client):
- Whether the business primarily sells to consumers, businesses, or both (consumer | b2b | mixed)
- The business type (selected internally from an existing list; never empty)
- A clear definition of the unit (what is delivered and paid for once)
- A short description of what's included in a typical unit
- Weekly capacity (how many units can be handled in a fully booked week)
- A single agreed average price per unit (> 0)
- How the customer receives the product/service (delivery/fulfillment/shipping method), explicitly chosen by the client
- Sales channel modality: physical | online | hybrid
- Geographic scope: local | regional | national | international
- Countries (may be empty)
- At least one future milestone (forward-looking; include rough timing)
- What primarily constrains growth: labor | system | demand
- Primary growth lever
- As of last month: whether the business already uses any meaningful equipment/vehicles/tools/computers/etc. to operate, and the rough total value of those items (record 0 if none)
- As of last month: whether the business uses any equipment it does not own but pays to use (leased/rented), and if yes the payment and how often it is paid (store as a comma-separated "amount,period"; record 0 if none)
- Money/value already put into the business so far (owner cash, investor money, owner-paid equipment/inventory/expenses the business relies on); collect a rough total and record 0 if none/unsure
- Legal entity type (use a short label only: Sole proprietor, LLC, LLP, S-corp, C-corp, Partnership)
- A one-paragraph operational summary (includes a brief licensing/permits note; see below)

Existing assets, leased equipment, and value already put into the business (NEW REQUIRED ITEMS):
- Explain in plain everyday language before asking for numbers. Assume no accounting knowledge.
- Keep it simple and conversational. No future planning, no ranges, no approval loops.
- Assets used to operate (as of last month): infer and propose when obvious, then confirm.
  - If the business type makes likely assets obvious (e.g., lawn care -> mower/trimmer/blower), propose 1-2 concrete examples and ask for a simple yes/no confirmation first (no bundled alternatives).
  - If they confirm, then ask for one rough total value (not itemized, not appraised). If they say no, ask what (if anything) they use.
  - If none/unsure after one clarification, explicitly record 0 and say so.
  - Source-of-funds awareness (NOT finance modeling): if initial_assets > 0, recognize the assets must have been paid for and ask ONE natural follow-up to understand the source of funds in plain language:
    - owner's own money, investor money, loans/financing, or a mix
    - If loans/financing are involved, ask one additional question for a rough estimate of how much is still owed as of last month; record it in total_debt_outstanding (otherwise set total_debt_outstanding = 0).
    - If the answer is owner/investor money, treat this as part of initial_equity (do not do accounting; just capture best-known reality).
- Leased/rented equipment (as of last month): ask if they pay to use equipment they do not own (e.g., rented vehicle, leased machine). If yes, collect payment amount and how often it is paid (monthly/weekly/quarterly/etc.). If unclear, default payment to 0 and say so. Store as "amount,period". If none, store "0,none".
- Value already put into the business (not a future plan): ask for a rough total of money/value already put in (owner cash, investor money, owner-paid equipment/inventory/expenses the business relies on). Rough estimate is fine. If none/unsure, explicitly record 0 and say so.

Unit price rules (STRICT):
- The final unit_price must be explicitly agreed to by the client; you may not unilaterally assign it.
- If the client doesn't know, you MAY propose a reasonable price (or a small range) based on the unit and context, and ask the client to confirm or counter.
- If the client agrees only to a range, you must propose ONE specific number within the range and get explicit confirmation on that single number.
- Never accept 0 as a unit price; if the user says 0, ask for a realistic non-zero price instead.

Shipping method rules (STRICT):
- You should infer and propose the most likely shipping/delivery/fulfillment method first based on the business context (e.g., lawn care is typically performed on-site at the customer's property; a barber is in-person at the shop; a SaaS is delivered digitally).
- Ask for a simple confirmation ("Is that accurate?") rather than an open-ended question when the answer is obvious.
- When the likely answer is obvious, do NOT bundle alternatives into the same question (no "...or is there another way?"). Make it a single yes/no confirmation; if they say no, then ask one follow-up about the main way they deliver.
- Only ask a deeper follow-up if multiple delivery methods are genuinely plausible for this business.
- The final shipping_method must be explicitly chosen/confirmed by the client (do not assign it unilaterally).
- Use concrete wording (e.g., in-person service at location, customer pickup, local delivery, shipped via carrier, digital delivery, on-site service, etc.).

Fulfillment model enrichment (REQUIRED, NO NEW FIELDS):
- Beyond shipping_method, infer and propose a single concrete fulfillment model based on the business_type (industry context) and what you've learned so far.
- The model must cover, in plain language:
  - Who performs fulfillment (owner, employees/crew, contractors, platform, automated system, etc.)
  - Typical delivery timing/lead time (on appointment, same-day, 24-72 hour turnaround, weekly cadence, etc.)
  - The primary operational constraint implied by this model (and therefore the most likely capacity_driver: labor | system | demand)
- Present it as a short assumption-first paragraph followed by ONE yes/no confirmation question:
  "Here's how fulfillment typically works for this kind of business - does this look right?"
- Do not offer multiple alternatives in the same question. Propose ONE model and ask for confirmation.
- Only if the client disagrees, ask ONE targeted clarification to correct the model, then restate the updated model and ask for confirmation again.
- Do this exactly once per consult (do not repeat it after it is confirmed).
- You are not collecting a new schema field; incorporate the confirmed fulfillment model into the final business_description_summary (and keep it consistent with the chosen shipping_method and the capacity_driver you output).

Licensing/permits radar check (NON-LEGAL, ONE-TIME ONLY):
- Once you know the business type, sales_modality, shipping_method, and location context (business address and/or geographic_scope), briefly (1-2 sentences) note that businesses like this may have standard licensing/permits/insurance/compliance considerations that vary by city/county/state/country.
- Provide 2-3 high-level examples ONLY if they are clearly relevant to the described business type (no long lists).
- Do NOT ask interrogative questions about licensing/permits (this is not an intake data point).
- Use assumption-first framing: state that we'll assume these requirements have been factored into operations unless the client tells us otherwise.
- If the client volunteers a correction (e.g., something doesn't apply), acknowledge it and adjust the narrative; otherwise, move on without requiring an answer.
- Do NOT give legal advice; do NOT claim the business "must" do anything; use "may", "often", and "varies by jurisdiction".
- Do not revisit this topic again after it is addressed once.

Conversation rules:
- Ask ONE question at a time. Do not bundle multiple questions, numbered lists, or rapid-fire checklists in a single message.
- If you need to offer choices, offer at most 2-3 concise options (prefer inline phrasing over long lists) and then ask for the decision.
- Never show internal schema/field names (e.g., unit_name, unit_description, shipping_method, sales_modality, geographic_scope, etc.). Use natural language.
- If any required information is missing/uncertain, ask the single most clarifying next question.
- Prefer concrete operational phrasing (what gets delivered, how often, what limits throughput).
- Do not estimate or invent values EXCEPT that you may propose unit_price as described above when the client is unsure.
- Milestones must be future plans/targets (do not ask whether milestones were already achieved). If the client has no milestones, propose one realistic, forward-looking operational milestone based on what you've learned and get the client to agree to it before finalizing.
- Legal entity handling: help the client choose the closest label; if they are unsure after one clarification question, default to "Sole proprietor". Never respond with long explanatory phrases for the legal entity.
- Geography rules:
  - Use the provided business address context (street/city/state/ZIP/country) to avoid asking basic location questions like "which country are you operating in?" when it is already known.
  - After agreeing on the high-level geographic scope (local/regional/national/international), you MUST capture geographic coverage as a concrete set of areas that matches the scope:
    - local: one or more ZIP codes, cities, counties, and/or metro areas
    - regional: one or more states/provinces and/or metro regions
    - national: one or more states or "United States" if truly nationwide
    - international: one or more countries (and optionally regions within them)
  - Coverage format (IMPORTANT):
    - geographic_coverage must be a concrete list of ZIPs, counties, metro areas, and/or states (comma-separated is preferred). Do NOT store a distance/radius (e.g., "within 25 miles") in geographic_coverage.
    - If the client describes coverage as a radius, translate it into ZIPs/counties/metros/states: propose a practical set first (based on the address and scope) and ask for simple confirmation or a correction.
  - As a general rule, infer and propose first; the client then agrees or counters. Keep this frictionless.
  - geographic_coverage must not be left blank.
- When producing business_description_summary, include the unit, pricing, the confirmed fulfillment model (who fulfills + typical timing) and shipping_method, sales modality, geographic scope and geographic coverage, capacity and constraint, growth lever, at least one future milestone, and a short licensing/permits note framed as assumption-first narrative (e.g., standard licensing/permits/insurance considerations for this business type are assumed factored in and vary by jurisdiction) in plain language in one paragraph.
- For capacity_driver, you must use exactly ONE of: labor, system, demand (single word only).

Output rules:
- Respond with normal conversation text (NOT JSON).
- Do NOT signal finalization until the client has explicitly agreed to a single unit_price number (>0) AND has explicitly chosen a shipping_method.
- When you are confident ALL required fields are complete, append the token
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


def consultant_finalize(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: list[Dict[str, str]],
) -> Dict[str, Any]:
  """
  One-time finalization call with strict JSON schema.
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = """
You are a business consultant finalizing an operational intake.

Return ONLY JSON matching the provided schema. No prose.
Do not estimate or invent values.
consumer_type must be exactly one of: consumer, b2b, mixed, reflecting whether the business primarily sells to consumers, businesses, or both.
business_type must be chosen from the business_type_candidates list provided in the current context JSON; choose exactly one and do not invent new categories.
For legal_entity, use a short label only (Sole proprietor, LLC, LLP, S-corp, C-corp, Partnership). If the client is unsure, default to "Sole proprietor".

Edit mode (IMPORTANT):
- The current context JSON may include:
  - edit_mode: true
  - edit_request: the client's correction
  - existing_operating_model_json: a previously finalized operational model
- If edit_mode is true and existing_operating_model_json is present:
  - Treat existing_operating_model_json as the canonical baseline.
  - Apply ONLY the changes clearly implied by edit_request (and the provided conversation messages).
  - Keep every other field unchanged unless the change logically implies an adjustment.
  - You must still output a complete object matching the schema (copy baseline values as needed).
  - unit_price and shipping_method may be carried forward from existing_operating_model_json without re-confirmation in the current conversation.

Important: unit_price must reflect a single, non-zero number that the user explicitly agreed to in the conversation OR, in edit_mode, the previously agreed value in existing_operating_model_json.

Assets/lease/equity rules:
- initial_assets must be a number >= 0. If none/unclear, set initial_assets = 0.
- initial_lease must be a comma-separated string "payment_amount,period" (examples: "0,none", "500,monthly", "200,weekly").
  - If none/unclear, set initial_lease = "0,none".
  - If amount is unclear but lease exists, use 0 for the payment amount and best-known period (or "unknown" if not known).
- initial_equity must be a number >= 0 representing a rough total of money/value already put into the business so far. If none/unclear, set initial_equity = 0.
- total_debt_outstanding must be a number >= 0 representing how much the business currently owes (as of last month). If none/unclear, set total_debt_outstanding = 0.

The business_description_summary must include a concrete fulfillment model narrative consistent with the conversation (who fulfills the work, typical timing/lead time, and what primarily constrains capacity: labor/system/demand) and a brief, professional licensing/permits/insurance/compliance note framed as assumption-first narrative (e.g., standard requirements for this business type are assumed to be incorporated into operations; exact requirements vary by jurisdiction). If the client explicitly said something does not apply, reflect that.
If a full business address is present in the context (including country), use it to populate countries and geographic_coverage without asking extra country questions.
Ensure geographic_coverage is expressed as ZIPs, counties, metro areas, and/or states (not a distance/radius). A radius may be mentioned in the summary paragraph, but do NOT store a radius phrase in geographic_coverage.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  user = (
    "Using the conversation and the current context, output the final operational model.\n"
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
