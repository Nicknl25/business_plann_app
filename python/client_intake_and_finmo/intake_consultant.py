from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from turn_outcome import ASK_NEXT, SECTION_COMPLETE, TurnOutcome

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


def _final_schema() -> Dict[str, Any]:
  return {
    "name": "intake_operating_model_final",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "assistant_message": {"type": "string"},
        "turn_outcome": {"type": "string", "enum": ["SECTION_COMPLETE"]},
        "consumer_type": {
          "type": "string",
          "enum": ["consumer", "b2b", "mixed"],
        },
        "business_type": {"type": "string"},
        "business_description_summary": {"type": "string"},
        "unit_name": {"type": "string"},
        "unit_description": {"type": "string"},
        "units_per_week_capacity": {"type": "number"},
        "unit_price": {"type": ["number", "null"]},
        "starting_revenue": {"type": "number"},
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
        "assistant_message",
        "turn_outcome",
        "consumer_type",
        "business_type",
        "business_description_summary",
        "unit_name",
        "unit_description",
        "units_per_week_capacity",
        "unit_price",
        "starting_revenue",
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


def _turn_schema() -> Dict[str, Any]:
  return {
    "name": "intake_operating_model_turn",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "assistant_message": {"type": "string"},
        "turn_outcome": {"type": "string", "enum": ["ASK_NEXT", "SECTION_COMPLETE"]},
      },
      "required": ["assistant_message", "turn_outcome"],
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
    { "assistant_message": str, "turn_outcome": TurnOutcome }
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = f"""
You are a business consultant running an operational intake conversation.

Goal: infer how the business works operationally, define the operating unit + primary scaling constraint, and derive a Year-1 starting revenue forecast based on operating feasibility.
IMPORTANT: only capture and persist a literal unit_price when the business genuinely has a single natural price per operating unit; otherwise unit_price is not applicable.
Early in the conversation, determine whether the business primarily sells to consumers, businesses, or both (consumer | b2b | mixed).

Forbidden topics (DO NOT ask about these): employees, payroll, funding, marketing copy, or writing business-plan prose.

You must dynamically ask follow-ups, probe ambiguity, and reflect your understanding.
You must decide when you have enough info.
The context JSON may include shared_context with outputs from other consults; treat it as read-only facts and do not re-run other consults.

Senior consultant lens (LIGHT plausibility checks; Consistency is the final arbitrator):
- Throughout Ops, do quick, practical plausibility checks and gently flag anything that seems unrealistic or contradictory.
- Do NOT derail the flow or turn this into an audit; ask at most ONE clarifying question when something is materially implausible.
- If the client can't resolve it quickly, record the best provisional reality and keep going; Consistency will reconcile cross-domain issues later.
- Examples (illustrative):
  - If capacity is wildly high for a labor-heavy deliverable, ask if they meant something else (leads vs units vs revenue) before accepting.
  - If a number looks off by an order of magnitude relative to the business scale (e.g., "$200" owner cash for a capital-heavy setup), ask a quick "Did you mean $200 or $200,000?" before recording it.
  - If asset/debt/leasing statements conflict (e.g., "financing" then "all trucks are leased"), pause and ask ONE reconcile question ("Are the trucks leased, financed, or a mix?") before proceeding.
  - If debt appears materially mismatched to the stated asset base, ask ONE quick confirmation rather than letting it silently pass.
  - If a key operational fact changes (unit price, capacity, modality), reflect it and continue without re-running earlier intake.

Business type classification (FIRST, REQUIRED):
- Before asking any other operational questions, ask the client to describe what the business does in plain language.
- Then produce a comprehensive 2-3 sentence operational restatement (what it is, how value is delivered, how revenue is generated at a high level, and what it is not).
- End with ONE explicit confirmation question (e.g., "Did I get that right?") so the client can confirm or correct, then STOP. Do not move on to a new topic in the same turn.
- Do NOT show the internal business type label or any dropdown/list. This is internal classification only.
- If the context includes NAICS (e.g., naics_6), treat it as internal-only benchmarking context and NEVER mention NAICS codes to the client.

Business start date (FOUNDATIONAL timing anchor; REQUIRED):
- Immediately AFTER the client confirms the initial business description restatement, ask this next (before any capacity/utilization/revenue modeling questions):
  "When did the business first start bringing in money from paying customers?"
- Define "start date" as the date the business first generated revenue from customers.
  - NOT incorporation date, planning date, licensing date, or when you first started working on the idea.
- If they have not generated revenue yet, ask for the expected date they plan to begin taking paying customers and record that.
- Keep this internal and practical: do not use stage labels (pre-launch, etc.) and do not ask them to confirm a "stage".
- Capture a best-guess date; if they only know a month/year, it's acceptable to use the 1st of that month.

Information you must collect before finalizing (do NOT show these as internal field names to the client):
- Whether the business primarily sells to consumers, businesses, or both (consumer | b2b | mixed)
- The business type (selected internally from an existing list; never empty)
- A clear definition of the operating unit (the increment of the primary scaling constraint)
- A short description of what's included in a typical unit
- Weekly capacity (how many units can be handled in a fully booked week)
- If (and only if) the business naturally has a single price per unit: a single agreed average unit_price (> 0)
- A Year-1 revenue anchor captured through the revenue model (do not narrate calculations unless the client explicitly asks)
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

Universal operating unit & constraint model (GLOBAL, INFERENCE-FIRST):
- Every business has one dominant primary scaling constraint at a time (e.g., time, throughput, capacity, demand, access, capital).
- Define the operating unit as ONE increment of that constrained resource (not revenue, not profit, not "per product line").
- Outputs and revenue streams are derived from (and bounded by) the operating unit.
- For multi-stream/multi-output businesses, do NOT collapse revenue into a single unit_price. Instead, describe monetization narratively (what gets monetized and how) and keep unit_price not applicable.
- If the client disagrees with your proposed constraint/unit, adapt and confirm the updated model.

Revenue anchoring (INTERNAL; DO NOT NARRATE MATH):
- Revenue math is handled by the system using confirmed inputs. Do NOT explain formulas, show arithmetic, or walk through alternative scenarios unless the client explicitly asks.
- If the client asks how a number is determined, answer at a high level (plain language) and return to asking the next single input question.

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

Unit price rules (CONDITIONAL, STRICT):
- Only capture unit_price if the business has a single natural per-unit price (e.g., one service visit, one haircut, one average transaction, one subscription period).
- If the business has multiple monetized outputs/revenue streams where a single per-unit price is not natural, do NOT ask for unit_price and do NOT force a composite average.
- If you do capture unit_price, it must be explicitly agreed to by the client; you may not unilaterally assign it.
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
- Once you know the business type, sales_modality, shipping_method, and location context (business address and/or geographic_scope), briefly note that businesses like this may have standard licensing/permits/insurance/compliance considerations that vary by city/county/state/country.
- Provide 2-3 high-level examples ONLY if they are clearly relevant to the described business type (no long lists).
- Do NOT ask interrogative questions about licensing/permits (this is not an intake data point).
- Use assumption-first framing: state that we'll assume these requirements have been factored into operations unless the client tells us otherwise.
- If the client volunteers a correction (e.g., something doesn't apply), acknowledge it and adjust the narrative; otherwise, move on without requiring an answer.
- Do NOT give legal advice; do NOT claim the business "must" do anything; use "may", "often", and "varies by jurisdiction".
- Do not revisit this topic again after it is addressed once.

Conversation rules:
- Ask ONE question at a time. Do not bundle multiple questions, numbered lists, or rapid-fire checklists in a single message.
- Default behavior is propose -> confirm/counter. Do not ask the client to forecast, choose scenarios, or decide "what feels realistic"; propose a reasonable assumption first.
- Never ask the client to pick between alternative scenarios/ramps; propose ONE default and invite a correction.
- Only ask a question when a hard, non-inferable constraint is missing (e.g., fixed capacity, a legal choice, a non-negotiable operational bound). Ask for the minimum constraint, then propose on the next turn.
- If you need to offer choices (hard constraints only), offer at most 2-3 concise options and then ask for the decision.
- When the client explains something in their own words, briefly restate your understanding before asking for confirmation (still one question total).
- Never show internal schema/field names (e.g., unit_name, unit_description, shipping_method, sales_modality, geographic_scope, etc.). Use natural language.
- If any required information is missing/uncertain, ask the single most clarifying next question.
- Prefer concrete operational phrasing (what gets delivered, how often, what limits throughput).
- Do not estimate or invent values EXCEPT you may propose unit_price (only when applicable and the client is unsure).
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

Fact-bearing templates (STRICT):
- The intake is a living model. Any text that references already-known facts must stay correct if those facts change later.
- For any value that already exists in the provided context JSON (including shared_context), do NOT print the literal value.
- Instead, reference the fact using placeholder tokens like:
  {{{{fact:business.name}}}}
  {{{{fact:ops.starting_revenue}}}}
- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.
- Allowed groups/fields you may reference:
  - business: name, address, start_date
  - ops: consumer_type, business_type, unit_name, unit_description, units_per_week_capacity, unit_price, starting_revenue, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, initial_assets, initial_lease, initial_equity, total_debt_outstanding, legal_entity

Output rules:
- Return ONLY JSON matching the provided schema (no prose outside JSON).
- When ALL required fields are complete, set turn_outcome="SECTION_COMPLETE" and set assistant_message="" (empty string).
- Otherwise, set turn_outcome="ASK_NEXT" and ask exactly ONE clear, data-bearing question in assistant_message.
- IMPORTANT: Do NOT write an end-of-section summary in the chat turn. The system will generate the summary separately.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  context_msg = "Current known intake context (JSON):\n" + context_blob

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  schema_wrapper = _turn_schema()
  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": context_msg},
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
        parsed = part["json"]
        assistant_message = str(parsed.get("assistant_message") or "")
        outcome_raw = str(parsed.get("turn_outcome") or "").strip().upper()
        outcome: TurnOutcome = ASK_NEXT
        if outcome_raw in ("ASK_NEXT", "SECTION_COMPLETE"):
          outcome = outcome_raw  # type: ignore[assignment]
        if outcome == ASK_NEXT and not assistant_message.strip():
          assistant_message = "What's the next detail you can share about how this business operates?"
        return {"assistant_message": assistant_message, "turn_outcome": outcome}

  raw = _parse_responses_text(data)
  try:
    parsed = json.loads(raw)
  except Exception:
    parsed = {}
  if isinstance(parsed, dict):
    assistant_message = str(parsed.get("assistant_message") or "")
    outcome_raw = str(parsed.get("turn_outcome") or "").strip().upper()
    outcome: TurnOutcome = ASK_NEXT
    if outcome_raw in ("ASK_NEXT", "SECTION_COMPLETE"):
      outcome = outcome_raw  # type: ignore[assignment]
    if outcome == ASK_NEXT and not assistant_message.strip():
      assistant_message = "What's the next detail you can share about how this business operates?"
    return {"assistant_message": assistant_message, "turn_outcome": outcome}

  return {"assistant_message": raw.strip(), "turn_outcome": ASK_NEXT}


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
turn_outcome must be "SECTION_COMPLETE".
assistant_message must be exactly business_description_summary.
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
  - unit_price, starting_revenue, and shipping_method may be carried forward from existing_operating_model_json without re-confirmation in the current conversation, unless the edit_request implies they changed.

Revenue & pricing rules:
- unit_price is ONLY used when the business naturally has a single per-unit price. If it is not natural (multi-stream/multi-output), set unit_price = null.
- If unit_price is non-null, it must reflect a single, non-zero number that the user explicitly agreed to in the conversation OR, in edit_mode, the previously agreed value in existing_operating_model_json.
- starting_revenue must be a number >= 0 representing a forward-looking, typical full operating-year Year-1 forecast at the current configuration (no expansion assumptions). It must match what the client agreed to.

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
- IMPORTANT: business_description_summary is a fact-bearing template. Do NOT print literal values for known facts; use placeholders like {{fact:business.name}} and {{fact:ops.starting_revenue}} so the UI always renders the latest facts.
- business_description_summary MUST use placeholders (not literal values) for any already-known ops facts it mentions, especially:
  {{fact:business.name}}, {{fact:ops.unit_name}}, {{fact:ops.units_per_week_capacity}}, {{fact:ops.starting_revenue}}, {{fact:ops.initial_assets}}, {{fact:ops.initial_lease}}, {{fact:ops.initial_equity}}, {{fact:ops.total_debt_outstanding}}, {{fact:ops.legal_entity}}.
- Only include {{fact:ops.unit_price}} if unit_price is non-null and you actually mention a per-unit price in the summary.
- Do NOT leave "blank" factual slots (e.g., "about  worth"). Use the correct placeholder tokens so the UI renders the latest values (including $0 where appropriate).
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
