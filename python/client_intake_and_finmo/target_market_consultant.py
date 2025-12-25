from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

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
    "name": "intake_target_market_final",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "gender_age_intent": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "gender_focus": {
                "type": "string",
                "enum": ["female", "male", "all"],
              },
              "age_min": {"type": "number"},
              "age_max": {"type": "number"},
            },
            "required": ["gender_focus", "age_min", "age_max"],
          },
        },
        "income_intent": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "income_min": {"type": "number"},
              "income_max": {"type": "number"},
            },
            "required": ["income_min", "income_max"],
          },
        },
        "selections": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "segment": {
                "type": "string",
                "enum": [
                  "Education",
                  "Household Structure",
                  "Housing Economics",
                  "Employment",
                ],
              },
              "acs_codes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["segment", "acs_codes"],
          },
        },
        "target_market_summary": {"type": "string"},
        "confidence": {"type": "number"},
      },
      "required": [
        "gender_age_intent",
        "income_intent",
        "selections",
        "target_market_summary",
        "confidence",
      ],
    },
  }


def target_market_chat_turn(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  Free-text target market consultant conversation turn (NO schema enforcement).

  Returns:
    { "assistant_message": str, "finalize_ready": bool }
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = f"""
You are a business consultant conducting a Target Market discovery consultation.

You MUST leverage the provided business context and reference it when making suggestions.

Goal:
- Determine who the business serves (target market) in a defensible, realistic way.
- Work segment by segment and narrow ambiguity with the client.
- You may suggest likely targets based on context, but the client must make the decision.

Segments to consult on (in this order):
1) Gender & Age
2) Income
3) Education
4) Optional segments decision (Household / Employment / Housing)
5) Household structure (ONLY if client opts in)
6) Employment (ONLY if client opts in)
7) Housing economics (ONLY if client opts in)

Rules:
- Default to ranges and breadth: multiple groups per segment is normal.
- Do not force artificial precision; single-point targets are rare.
- Never show ACS codes to the user.
- Handle ONE segment at a time. Do not preview or list upcoming segments or questions.
- Keep messages concise: ask one question at a time and offer at most 2–3 suggested options unless the user asks for more.
- Avoid pressuring "please confirm / once you confirm / let's lock this in" loops. Treat the user's answer to your question as the decision, briefly reflect it back, and move on. Only ask a follow-up if the answer is ambiguous or incomplete.
- The user may revise earlier choices at any time; accept the revision and continue without restarting the consult.
- Do not consult or discuss any other segments.
- For Gender & Age and Income, prefer collecting a clear numeric range (min and max). If the user answers qualitatively (e.g., "middle income"), propose a reasonable numeric range based on the business context and ask whether that range is acceptable or how they'd adjust it.
- Employment and Housing Economics are OPTIONAL and should not be a long, drawn-out process:
  - After finishing Education, briefly state whether you think Household Structure, Employment and/or Housing Economics are relevant (1–2 sentences total, grounded in the business context).
  - Then ask the client to choose: include Household Structure, include Employment, include Housing, include any combination, or skip all three.
  - If the client says skip, do not discuss those segments at all.
  - If the client opts in, handle one optional segment at a time, with minimal questions.

Output rules:
- Respond with normal conversation text (NOT JSON).
- When you have enough information to finalize (all required segments decided, and any optional segments handled/skipped), end with a short recap + "Target market intake complete.", then append the token {FINALIZE_TOKEN} on its own line at the very end of your message.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  context_msg = (
    "Prior business context from the operational consult (JSON):\n" + context_blob
  )

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


def target_market_finalize(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  mapping_rows: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  One-time finalization call with strict JSON schema.

  The model must only select ACS codes from mapping_rows and keep codes within the segment.
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = """
You are a business consultant finalizing a Target Market intake.

Return ONLY JSON matching the provided schema. No prose.

Hard requirements:
- For Gender & Age and Income: DO NOT output ACS codes directly.
  - Populate gender_age_intent and income_intent from the conversation.
  - Do NOT include "Gender & Age" or "Income" in selections; the backend will map the intent to codes.
- selections must include segment names exactly as in the mapping table.
- acs_codes must be selected ONLY from the mapping table.
- Do not invent codes.
- Do not cross segments: each code must belong to the segment it is listed under.
- Default to multiple codes per segment to represent ranges/breadth; single-code choices should be rare.
- Required segments: Gender & Age, Income, Education, Household Structure.
- Required segments: Gender & Age, Income, Education.
- Optional segments (include ONLY if the client opted in): Household Structure, Employment, Housing Economics. If the conversation never discussed an optional segment, DO NOT include it.
- If the client explicitly chose to skip a segment, DO NOT include the skipped segment.
- target_market_summary must be one comprehensive paragraph in human-readable language that reflects the full consultation across segments.
- The mapping table includes min_value and max_value (numeric) for some rows (notably Gender & Age and Income). Use them to be precise:
  - When the client specifies a numeric range (e.g., age 19–58 or income $40k–$120k), select ALL mapping rows whose [min_value, max_value] overlaps that intended range.
  - If the client’s boundary falls between buckets, include the nearest bucket that covers it (e.g., min 19 should include an 18–24 bucket; max 58 should include a 55–64 bucket).
  - If Gender is intended to be all genders, include both male and female rows for the selected age buckets; if a specific gender focus was chosen, include only that gender’s rows.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  mapping_blob = json.dumps(mapping_rows, ensure_ascii=False)
  user = (
    "Use the conversation and the prior business context to finalize target market selections.\n"
    "Prior business context (JSON):\n"
    f"{context_blob}\n\n"
    "Target market mapping table rows (JSON array of {acs_code, description, segment, min_value, max_value}):\n"
    f"{mapping_blob}\n"
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
