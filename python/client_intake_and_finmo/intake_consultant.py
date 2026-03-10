from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

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
        "business_stage": {"type": ["string", "null"]},
        "business_description_summary": {"type": "string"},
        "lob_models": {
          "type": ["array", "null"],
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "lob_name": {"type": "string"},
              "products": {
                "type": "array",
                "minItems": 1,
                "items": {
                  "type": "object",
                  "additionalProperties": False,
                  "properties": {
                    "product_name": {"type": "string"},
                    "unit_name": {"type": "string"},
                    "unit_description": {"type": "string"},
                    "unit_cadence": {"type": "string", "enum": ["weekly", "monthly", "contract"]},
                    "units_per_week_capacity": {"type": "number"},
                    "units_per_period_capacity": {"type": "number"},
                    "operating_periods_per_year": {"type": ["number", "null"]},
                    "utilization_rate": {"type": ["number", "null"]},
                    "unit_price": {"type": "number"},
                  },
                  "required": [
                    "product_name",
                    "unit_name",
                    "unit_description",
                    "unit_cadence",
                    "units_per_week_capacity",
                    "units_per_period_capacity",
                    "operating_periods_per_year",
                    "utilization_rate",
                    "unit_price",
                  ],
                },
              },
            },
            "required": ["lob_name", "products"],
          },
        },
        "unit_name": {"type": ["string", "null"]},
        "unit_description": {"type": ["string", "null"]},
        "unit_cadence": {"type": ["string", "null"], "enum": ["weekly", "monthly", "contract", None]},
        "units_per_week_capacity": {"type": ["number", "null"]},
        "units_per_period_capacity": {"type": ["number", "null"]},
        "operating_periods_per_year": {"type": ["number", "null"]},
        "utilization_rate": {"type": ["number", "null"]},
        "unit_price": {"type": ["number", "null"]},
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
        "legal_entity": {"type": "string"},
        "confidence": {"type": "number"},
      },
      "required": [
        "consumer_type",
        "business_type",
        "business_stage",
        "business_description_summary",
        "lob_models",
        "unit_name",
        "unit_description",
        "unit_cadence",
        "units_per_week_capacity",
        "units_per_period_capacity",
        "operating_periods_per_year",
        "utilization_rate",
        "unit_price",
        "shipping_method",
        "sales_modality",
        "geographic_scope",
        "geographic_coverage",
        "countries",
        "milestones",
        "capacity_driver",
        "primary_growth_lever",
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
    { "assistant_message": str, "finalize_ready": bool, "patch": dict }
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = f"""
You are a business consultant running an operational intake conversation.

Goal: infer how the business works operationally and capture agreed unit pricing per product (single or multi-product).
Early in the conversation, determine whether the business primarily sells to consumers, businesses, or both (consumer | b2b | mixed).

Forbidden topics (DO NOT ask about these): total revenue, employees, payroll, funding, marketing copy, or writing business-plan prose.

You must dynamically ask follow-ups, probe ambiguity, and reflect your understanding.
You must decide when you have enough info.
The context JSON may include shared_context with outputs from other consults; treat it as read-only facts and do not re-run other consults.

Senior consultant lens (LIGHT plausibility checks; Consistency is the final arbitrator):
- Throughout Ops, do quick, practical plausibility checks and gently flag anything that seems unrealistic or contradictory.
- Do NOT derail the flow or turn this into an audit; ask at most ONE clarifying question when something is materially implausible.
- If the client can't resolve it quickly, record the best provisional reality and keep going; Consistency will reconcile cross-domain issues later.
- Examples (illustrative):
  - If capacity is wildly high for a labor-heavy deliverable, ask if they meant something else (leads vs units vs revenue) before accepting.
  - If a key operational fact changes (unit price, capacity, modality), reflect it and continue without re-running earlier intake.

Business type classification (FIRST, REQUIRED):
- Before asking any other operational questions, classify the business type using a short professional clarification exchange.
- Ask the client to describe what the business does in plain language.
- Keep the first client answer as light as possible. Explicitly invite them to start with a simple label like "fitness gym", "law firm", "restarant", etc. (do NOT ask them to add details).
- Your first question should follow this exact pattern:
  "To get us started, could you describe in plain language what \"{{fact:business.name}}\" does or will do-what you sell or deliver, and how you expect to get paid for it (if it's easier, you can start with something simple like \"fitness gym\", \"law firm\", \"restarant\", etc.)?"
- Then produce a comprehensive 2-3 sentence operational restatement (what it is, how value is delivered, how revenue is generated at a high level, and what it is not), explicitly stating the unit cadence (weekly, monthly, or contract) and ask for confirmation.
- If the client corrects you or if the description is ambiguous, ask ONE clarifying question, then restate again and confirm.
- Do not proceed to the rest of the operational intake until the client confirms the restatement.
- The confirmation must be a single explicit question sentence ending with "?" and nothing else after it.
- Cadence confirmation happens here as part of the restatement (not as a separate form choice).
- Do NOT ask who they serve (consumer vs business) before the restatement is confirmed.
- After the restatement is confirmed, ask the consumer vs business question as a stand-alone message.
- Do NOT show the internal business type label or any dropdown/list. This is internal classification only.

Business stage inference (RIGHT AFTER BUSINESS TYPE CONFIRMATION):
- If business_stage_hint is provided in context, use it directly.
- Otherwise, use the business_start_date provided in context (the date the client entered) to infer stage.
- Use current_date provided in context to judge timing.
- Stage rules:
  - If business_start_date is in the future -> pre-revenue.
  - If business_start_date is within the last 12 months -> early-stage.
  - If business_start_date is more than 12 months ago -> operating.
- After the business type restatement is confirmed and BEFORE asking who they serve, state a short assumption using this format:
  "Based on the start date you provided, I'm treating this as <stage> for planning context."
  Add: "If that's off, tell me and I'll adjust."
- Do not ask the client to supply any extra cues about stage.

Multiple lines of business (LOB) and products (EARLY, REVENUE-DRIVEN):
- A LOB means distinct operations. Listen for this in the first "what does the business do?" answer.
- If multiple distinct operations are described or clearly implied, propose splitting them into separate LOBs and confirm in one short question before proceeding.
- If the client prefers to keep them combined, treat it as a single LOB.
- When defining the unit, if the client mentions more than one distinct unit/product, propose tracking multiple products and confirm.
- If multiple LOBs/products are confirmed, capture unit_name, unit_description, unit_cadence, units_per_period_capacity, unit_price, and units_per_week_capacity for each product, one product at a time.
- For each product, also capture a Year-1 practical utilization rate as a percentage of practical capacity (for example 70%).
- Do NOT ask the client to choose a "primary" product when multiple are confirmed.

Information you must collect before finalizing (do NOT show these as internal field names to the client):
- Whether the business primarily sells to consumers, businesses, or both (consumer | b2b | mixed)
- The business type (selected internally from an existing list; never empty)
- Business stage inferred from the provided start date (pre-revenue | early-stage | operating), or null if no start date
- A clear definition of the unit for each product (what is delivered and paid for once)
- A short description of what's included in a typical unit (per product)
- Unit cadence (weekly, monthly, or contract) for each product
- Capacity per cadence period (how many units can be handled in a fully booked period, per product)
- Operating periods/turns per year for each product when needed for revenue planning
- Year-1 practical utilization rate per product (as a percent of practical capacity)
- A single agreed average price per unit (> 0) for each product
- How the customer receives the product/service (delivery/fulfillment/shipping method), explicitly chosen by the client
- Sales channel modality: physical | online | hybrid
- Geographic scope: local | regional | national | international
- Countries (may be empty)
- What primarily constrains growth: labor | system | demand
- Primary growth lever
- Legal entity type (use a short label only: Sole proprietor, LLC, LLP, S-corp, C-corp, Partnership)
- A one-paragraph operational summary (includes a brief licensing/permits note; see below)

Cadence handling (REQUIRED):
- Infer the most likely unit cadence from the business model (weekly, monthly, or contract) and confirm it as part of the restatement.
- weekly: capacity is per week.
- monthly: capacity is per month.
- contract: capacity is the maximum number of active projects/contracts you can handle at the same time (concurrency-first), NOT the total number completed in a year.
- If the unit represents owned assets/inventory (rentals, storage units, rooms, vehicles, seats, etc.), treat capacity as the count of those units available in a typical period and keep the language plain. Do not frame this as throughput or a "mapping" choice; just restate the business normally and confirm.
- Always populate units_per_period_capacity based on the chosen cadence.
- For compatibility, also populate units_per_week_capacity with the same numeric value (even for monthly/contract cadences).

Periods-per-year handling (REQUIRED):
- operating_periods_per_year is the number of planning periods/turns per year for each product.
- weekly cadence implies 52 operating periods per year unless the client explicitly changes it.
- monthly cadence implies 12 operating periods per year unless the client explicitly changes it.
- contract cadence does NOT have an automatic final answer. Infer and propose the most likely annual turns assumption first, then let the client agree or counter in plain language.
- For contract-cadence products, ask/propose operating_periods_per_year during the normal Ops conversation after utilization is agreed and before the end-of-Ops wrap-up. Do not defer this to a final summary or late controller correction.
- For contract cadence, explain turns/year as how many times ONE active project slot turns over in a year. Do NOT describe it as total annual events unless the client explicitly chooses to think about it that way.
- If the client gives a total annual-events answer while you are trying to capture turns/year, do NOT overwrite the already-agreed concurrent capacity. Keep the capacity unchanged and either (a) translate that annual total into an implied turns/year assumption and confirm it, or (b) ask one short clarification if the numbers do not make sense together.
- Once concurrent capacity for a contract product has been agreed, never reinterpret that same number later as annual throughput.
- Keep the question plain and client-friendly; do not ask the client to do finance math.
- Store operating_periods_per_year as a numeric value for each product.
- Do not finalize Ops until operating_periods_per_year has been explicitly agreed for every contract-cadence product in scope.

Utilization handling (REQUIRED):
- After capacity is agreed for a product, capture a Year-1 practical utilization rate for that product.
- utilization_rate is the average share of practical capacity you expect to actually use in Year 1.
- Store utilization_rate as a decimal fraction (for example 70% -> 0.7, 85% -> 0.85).
- Propose a practical utilization assumption first, then let the client agree or counter.
- Keep the question plain: do not ask the client to do math; they may answer in percent language ("70%", "about 80 percent", "closer to 65").
- Do not finalize Ops until utilization_rate has been explicitly agreed for every product in scope.

Unit price rules (STRICT):
- The final unit_price for each product must be explicitly agreed to by the client; you may not unilaterally assign it.
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
  "That is how fulfillment typically works for this kind of business - does this look right?"
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
- Do NOT re-ask a field that has already been explicitly answered and acknowledged unless the client changed it, contradicted it, or the earlier answer truly did not resolve the field.
- Never show internal schema/field names (e.g., unit_name, unit_description, shipping_method, sales_modality, geographic_scope, etc.). Use natural language.
- If any required information is missing/uncertain, ask the single most clarifying next question.
- Prefer concrete operational phrasing (what gets delivered, how often, what limits throughput).
- Do not estimate or invent values EXCEPT that you may propose unit_price as described above when the client is unsure.
- Legal entity handling: help the client choose the closest label; if they are unsure after one clarification question, default to "Sole proprietor". Never respond with long explanatory phrases for the legal entity.
- Legal entity confirmation (REQUIRED): ask and confirm the legal structure as a stand-alone question after the restatement is confirmed and before the final summary. Do NOT bundle it with any other question.
- Do NOT generate a final operational summary paragraph. End-of-Ops wrap-up is controller-owned.
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
- When producing business_description_summary, include the unit, cadence, pricing, the confirmed fulfillment model (who fulfills + typical timing) and shipping_method, sales modality, geographic scope and geographic coverage, capacity and constraint, growth lever, and a short licensing/permits note framed as assumption-first narrative (e.g., standard licensing/permits/insurance considerations for this business type are assumed factored in and vary by jurisdiction) in plain language in one paragraph.
- If cadence is not weekly, do not mention "mirroring" or weekly capacity language in the summary; keep the capacity phrasing aligned to the confirmed cadence and the unit.
- For capacity_driver, you must use exactly ONE of: labor, system, demand (single word only).

Fact-bearing templates (STRICT):
- The intake is a living model. Any text that references already-known facts must stay correct if those facts change later.
- For any value that already exists in the provided context JSON (including shared_context), do NOT print the literal value.
- Instead, reference the fact using placeholder tokens like:
  {{{{fact:business.name}}}}
  {{{{fact:ops.unit_price}}}}
- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.
- Allowed groups/fields you may reference:
  - business: name, address, start_date
  - ops: consumer_type, business_type, unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, unit_price, shipping_method, sales_modality, geographic_scope, geographic_coverage, countries, milestones, capacity_driver, primary_growth_lever, legal_entity

Output rules:
- Return ONLY JSON matching this schema (no prose outside JSON):
  {{
    "assistant_message": string,  // normal conversation text
    "finalize_ready": boolean,   // true only when all required fields are complete (see below)
    "is_restatement_confirmation_prompt": boolean,  // true only for the business-type restatement confirmation prompt
    "patch": object  // incremental Ops facts for this turn; unknown/no-change fields must be null
  }}
- patch rules (IMPORTANT):
  - Use patch to persist structured Ops facts incrementally during the conversation.
  - If a fact becomes clear on this turn, include it in patch.
  - If a fact is still unknown or unchanged, return null for that field.
  - For multi-product flows, lob_models must be the full current structured snapshot of the known products so far; carry forward already-known products from the context JSON and do not drop them.
  - For not-yet-known fields inside a product, return null for those product fields.
  - Normalize enums where known:
    - unit_cadence: weekly, monthly, contract
    - sales_modality: physical, online, hybrid
    - capacity_driver: labor, system, demand
- finalize_ready must be false until the client has explicitly agreed to unit_price(s) for all products in scope, confirmed unit cadence, AND has explicitly chosen a shipping_method.
- finalize_ready must also remain false until utilization_rate has been explicitly agreed for every product in scope.
- finalize_ready must also remain false until operating_periods_per_year has been explicitly agreed for every contract-cadence product in scope.
- When finalize_ready is true:
  - assistant_message must be a short handoff message only, or an empty string.
  - Do NOT include an operational summary, confirmation paragraph, bullets, lists, headings, or extra restatements.
- is_restatement_confirmation_prompt must be true if and only if assistant_message is the business-type restatement confirmation prompt described under "Business type classification (FIRST, REQUIRED)" (the 2-3 sentence operational restatement ending with the single explicit confirmation question). It must be false for all other messages, including the end-of-Ops handoff.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  context_msg = "Current known intake context (JSON):\n" + context_blob

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  schema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "assistant_message": {"type": "string"},
      "finalize_ready": {"type": "boolean"},
      "is_restatement_confirmation_prompt": {"type": "boolean"},
      "patch": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "consumer_type": {"type": ["string", "null"]},
          "business_type": {"type": ["string", "null"]},
          "unit_name": {"type": ["string", "null"]},
          "unit_description": {"type": ["string", "null"]},
          "unit_cadence": {
            "type": ["string", "null"],
            "enum": ["weekly", "monthly", "contract", None],
          },
          "units_per_week_capacity": {"type": ["number", "null"]},
          "units_per_period_capacity": {"type": ["number", "null"]},
          "operating_periods_per_year": {"type": ["number", "null"]},
          "utilization_rate": {"type": ["number", "null"]},
          "unit_price": {"type": ["number", "null"]},
          "shipping_method": {"type": ["string", "null"]},
          "sales_modality": {
            "type": ["string", "null"],
            "enum": ["physical", "online", "hybrid", None],
          },
          "geographic_scope": {"type": ["string", "null"]},
          "geographic_coverage": {"type": ["string", "null"]},
          "countries": {"type": ["array", "null"], "items": {"type": "string"}},
          "capacity_driver": {
            "type": ["string", "null"],
            "enum": ["labor", "system", "demand", None],
          },
          "primary_growth_lever": {"type": ["string", "null"]},
          "legal_entity": {"type": ["string", "null"]},
          "lob_models": {
            "type": ["array", "null"],
            "items": {
              "type": "object",
              "additionalProperties": False,
              "properties": {
                "lob_name": {"type": "string"},
                "products": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                      "product_name": {"type": ["string", "null"]},
                      "unit_name": {"type": ["string", "null"]},
                      "unit_description": {"type": ["string", "null"]},
                      "unit_cadence": {
                        "type": ["string", "null"],
                        "enum": ["weekly", "monthly", "contract", None],
                      },
                      "units_per_week_capacity": {"type": ["number", "null"]},
                      "units_per_period_capacity": {"type": ["number", "null"]},
                      "operating_periods_per_year": {"type": ["number", "null"]},
                      "utilization_rate": {"type": ["number", "null"]},
                      "unit_price": {"type": ["number", "null"]},
                    },
                    "required": [
                      "product_name",
                      "unit_name",
                      "unit_description",
                      "unit_cadence",
                      "units_per_week_capacity",
                      "units_per_period_capacity",
                      "operating_periods_per_year",
                      "utilization_rate",
                      "unit_price",
                    ],
                  },
                },
              },
              "required": ["lob_name", "products"],
            },
          },
        },
        "required": [
          "consumer_type",
          "business_type",
          "unit_name",
          "unit_description",
          "unit_cadence",
          "units_per_week_capacity",
          "units_per_period_capacity",
          "operating_periods_per_year",
          "utilization_rate",
          "unit_price",
          "shipping_method",
          "sales_modality",
          "geographic_scope",
          "geographic_coverage",
          "countries",
          "capacity_driver",
          "primary_growth_lever",
          "legal_entity",
          "lob_models",
        ],
      },
    },
    "required": ["assistant_message", "finalize_ready", "is_restatement_confirmation_prompt", "patch"],
  }
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
        "name": "ops_consult_chat_turn",
        "schema": schema,
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
        obj = part["json"]
        return {
          "assistant_message": str(obj.get("assistant_message") or "").strip(),
          "finalize_ready": bool(obj.get("finalize_ready", False)),
          "is_restatement_confirmation_prompt": bool(
            obj.get("is_restatement_confirmation_prompt", False)
          ),
          "patch": obj.get("patch") if isinstance(obj.get("patch"), dict) else {},
        }

  # Fallback: parse output_text as JSON (should be rare with strict schema).
  raw = _parse_responses_text(data)
  parsed = json.loads(raw)
  if not isinstance(parsed, dict):
    raise RuntimeError("Ops consultant turn did not return a JSON object.")
  return {
    "assistant_message": str(parsed.get("assistant_message") or "").strip(),
    "finalize_ready": bool(parsed.get("finalize_ready", False)),
    "is_restatement_confirmation_prompt": bool(parsed.get("is_restatement_confirmation_prompt", False)),
    "patch": parsed.get("patch") if isinstance(parsed.get("patch"), dict) else {},
  }


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
business_stage rules:
- If business_stage_hint is provided in context, use it directly.
- Otherwise, use business_start_date (from context) and current_date (from context) to infer stage:
  - future start date -> pre-revenue
  - within last 12 months -> early-stage
  - more than 12 months ago -> operating
- If business_start_date or current_date is missing/invalid, set business_stage = null.
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
unit_cadence must be exactly one of: weekly, monthly, contract, based on how the client gets paid.
units_per_period_capacity must be provided for each product; for monthly or contract cadence, mirror that value into units_per_week_capacity for compatibility.
operating_periods_per_year must be included for each product as a number. For weekly/monthly cadence, use the implied annual value unless the client explicitly changed it. For contract cadence, carry forward the confirmed turns-per-year assumption unless the edit request clearly changes it.
utilization_rate must be included for each product as a decimal fraction of practical Year-1 utilization (for example 0.7 for 70%). In edit_mode, carry forward the baseline value unless the edit request clearly changes it.

The business_description_summary must include a concrete fulfillment model narrative consistent with the conversation (who fulfills the work, typical timing/lead time, and what primarily constrains capacity: labor/system/demand) and a brief, professional licensing/permits/insurance/compliance note framed as assumption-first narrative (e.g., standard requirements for this business type are assumed to be incorporated into operations; exact requirements vary by jurisdiction). If the client explicitly said something does not apply, reflect that.
If a full business address is present in the context (including country), use it to populate countries and geographic_coverage without asking extra country questions.
Ensure geographic_coverage is expressed as ZIPs, counties, metro areas, and/or states (not a distance/radius). A radius may be mentioned in the summary paragraph, but do NOT store a radius phrase in geographic_coverage.
- IMPORTANT: business_description_summary is a fact-bearing template. Do NOT print literal values for known facts; use placeholders like {{fact:business.name}} and {{fact:ops.unit_price}} so the UI always renders the latest facts.
- business_description_summary MUST use placeholders (not literal values) for any already-known ops facts it mentions, especially:
  {{fact:business.name}}, {{fact:ops.unit_name}}, {{fact:ops.unit_cadence}}, {{fact:ops.unit_price}}, {{fact:ops.units_per_week_capacity}}, {{fact:ops.units_per_period_capacity}}, {{fact:ops.legal_entity}}.
- Do NOT leave "blank" factual slots (e.g., "about  worth"). If a value is unknown or zero, still include the correct placeholder so the UI renders $0/none.
Multi-LOB/products:
- If the conversation confirms multiple LOBs and/or multiple products, populate lob_models accordingly.
- For lob_models, include each LOB name and one or more products with their unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, operating_periods_per_year, utilization_rate, and unit_price.
- When multiple LOBs or multiple products are confirmed, set top-level unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, operating_periods_per_year, and unit_price to null.
- When only one LOB with one product is confirmed, set top-level unit fields, top-level operating_periods_per_year, and top-level utilization_rate to that single product.
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
