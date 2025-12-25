from __future__ import annotations

import json
import os
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


def _final_schema() -> Dict[str, Any]:
  return {
    "name": "intake_operating_model_final",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
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
        "countries": {"type": "array", "items": {"type": "string"}},
        "milestones": {
          "type": "array",
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
        "business_description_summary",
        "unit_name",
        "unit_description",
        "units_per_week_capacity",
        "unit_price",
        "shipping_method",
        "sales_modality",
        "geographic_scope",
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
    { "assistant_message": str, "finalize_ready": bool }
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = f"""
You are a business consultant running an operational intake conversation.

Goal: infer how the business works operationally and capture a single, agreed unit price.

Forbidden topics (DO NOT ask about these): total revenue, employees, payroll, funding, marketing copy, or writing business-plan prose.

You must dynamically ask follow-ups, probe ambiguity, and reflect your understanding.
You must decide when you have enough info.

Required fields (must be complete before you signal finalization):
- business_description_summary (ONE comprehensive paragraph, human-readable; must capture the entire consultation and how the business operates; not marketing copy)
- unit_name
- unit_description
- units_per_week_capacity
- unit_price (average price per unit; MUST be a single number > 0)
- shipping_method (how the customer receives the product/service; MUST be explicitly chosen by the client)
- sales_modality: physical | online | hybrid
- geographic_scope: local | regional | national | international
- countries: list (may be empty)
- milestones: list of {{description, timing}} (may be empty)
- capacity_driver: labor | system | demand
- primary_growth_lever
- legal_entity (e.g., LLC, LLP, S-corp, C-corp, sole proprietorship, partnership)

Unit price rules (STRICT):
- The final unit_price must be explicitly agreed to by the client; you may not unilaterally assign it.
- If the client doesn't know, you MAY propose a reasonable price (or a small range) based on the unit and context, and ask the client to confirm or counter.
- If the client agrees only to a range, you must propose ONE specific number within the range and get explicit confirmation on that single number.
- Never accept 0 as a unit price; if the user says 0, ask for a realistic non-zero price instead.

Shipping method rules (STRICT):
- You may propose plausible shipping/delivery/fulfillment options based on the business context.
- The final shipping_method must be explicitly chosen/confirmed by the client (do not assign it unilaterally).
- Use concrete wording (e.g., in-person service at location, customer pickup, local delivery, shipped via carrier, digital delivery, on-site service, etc.).

Conversation rules:
- If any required field is missing/uncertain, ask the single most clarifying next question.
- Prefer concrete operational phrasing (what gets delivered, how often, what limits throughput).
- Do not estimate or invent values EXCEPT that you may propose unit_price as described above when the client is unsure.
- When producing business_description_summary, include the unit, pricing, fulfillment/shipping_method, sales modality, geography, capacity and constraint, growth lever, and milestones in plain language in one paragraph.
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

  resp = requests.post(url, headers=headers, json=payload, timeout=60)
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

Important: unit_price must reflect a single, non-zero number that the user explicitly agreed to in the conversation. If the user did not explicitly agree to a specific number, you must NOT finalize.
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

  resp = requests.post(url, headers=headers, json=payload, timeout=60)
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
