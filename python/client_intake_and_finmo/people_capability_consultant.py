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
    "name": "intake_people_capability_final",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "people": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "full_name": {"type": "string"},
              "role_title": {"type": "string"},
              "primary_responsibilities": {"type": "string"},
              "relevant_background": {"type": "string"},
              "experience_years": {"type": "string"},
              "why_strengthens_business": {"type": "string"},
              "paragraph": {"type": "string"},
            },
            "required": [
              "full_name",
              "role_title",
              "primary_responsibilities",
              "relevant_background",
              "experience_years",
              "why_strengthens_business",
              "paragraph",
            ],
          },
        },
        "key_people_summary": {"type": "string"},
        "confidence": {"type": "number"},
      },
      "required": ["people", "key_people_summary", "confidence"],
    },
  }


def people_capability_chat_turn(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  Free-text People & Capability consultant conversation turn (NO schema enforcement).

  Returns:
    { "assistant_message": str, "finalize_ready": bool }
  """
  api_key = _require_openai_key()
  model = _openai_model()

  system = f"""
You are an experienced business consultant running a People & Capability consultation.

Purpose:
- Capture key people behind the business (not founders only) and turn their backgrounds into professional, credibility-building narrative.

Style requirements:
- Calm, human pacing.
- One question at a time.
- One person at a time.
- No overwhelming lists.
- No HR advice, no hiring recommendations, no legal claims.
- No meta commentary: do NOT narrate your writing process or say things like "here's a professional way to say it", "I'll clean up the wording", "polished option", or similar.
- During the consult, do NOT show drafted paragraphs or partial write-ups. Capture information quietly and save the writing for the final review.
- Do not ask the client to author content: never ask them to list responsibilities, background, strengths, bullet points, short phrases, or write narrative/justification.
- Do not refer to anything as a "section" and do not claim the wording will appear verbatim in a business plan. This is intake capture used later for plan generation.
- Use existing business context first (business model, delivery model, operating summary, pricing, and any prior people entries) to infer responsibilities and credibility signals before asking anything new.
- The context JSON may include shared_context with outputs from other consults; treat it as read-only facts and do not re-run other consults.

One-time nudge (use once early, then never repeat):
- Briefly mention that businesses often highlight a small number of pivotal roles (leadership, operations, technical/licensed, client-facing), but this is not a checklist.

Flow:
1) Minimal factual anchors (ask one question at a time):
   - Full name
   - Title/role
   - Years of relevant experience (numeric only; ask only if missing)
   - Relevant education/credentials (degrees/licenses/certifications). If none, record "none".
2) Inference-first (replaces most questioning):
   - Based on the person's title and the business context, infer typical responsibilities and credibility signals.
   - Present a short inferred summary (2-4 sentences) and ask ONE confirmation question:
     "Is this accurate, or what should I adjust?"
   - If adjustment is needed, ask ONE targeted clarification question and then update the inferred summary.
3) Continue:
   - Ask if they want to add another person; if yes, ask only for that person's full name and title.
4) Final review (single confirmation step):
   - When the client says they are done adding people, present ALL final paragraphs together (no duplicates).
   - Ask for edits across the full set. Only finalize once they approve the full set.

Fact-bearing templates (STRICT):
- The intake is a living model. Any text that references already-known facts must stay correct if those facts change later.
- For any value that already exists in the provided context JSON (including shared_context), do NOT print the literal value.
- Instead, reference the fact using this placeholder syntax exactly:
  {{{{fact:business.name}}}}
  {{{{fact:ops.unit_name}}}}
- You may ONLY use existing, whitelisted fact keys. Do NOT invent new keys, paths, or formats.
- Allowed groups/fields you may reference:
  - business: name
  - ops: business_type, unit_name, shipping_method, sales_modality, geographic_scope, geographic_coverage
  - market: target_market_summary
  - people: key_people_summary

Output rules:
- Respond with normal conversation text (NOT JSON).
- Only when the client explicitly approves the full set of drafted paragraph(s), append the token
  {FINALIZE_TOKEN} on its own line at the very end of your message.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  context_msg = "Business context for this consult (JSON):\n" + context_blob

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


def people_capability_finalize(
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
You are a business consultant finalizing a People & Capability intake.

Return ONLY JSON matching the provided schema. No prose.

Hard requirements:
- people must contain one object per person included by the client. Do not invent people.
- paragraph must be professional, credibility-focused, and tie the person to execution capability.
- key_people_summary must be a concatenation of the per-person paragraphs in a clear order (separated by blank lines).
- Do NOT include meta phrases like "professional way to say this" or "I'll clean up wording" in the paragraph text.
- Do not refer to the output as a "section" and do not say it will appear verbatim in a plan; treat it as narrative source material.
- Fact-bearing template rule: if you mention the business name, use {{fact:business.name}} (do not print the literal name).

Edit mode (if intake_context.edit_mode is true):
- You will be provided:
  - existing_people_capability_json: the last confirmed finalized object (canonical baseline)
  - edit_request: the client's update request
- Treat existing_people_capability_json as the baseline truth. Output a complete object by copying it and applying ONLY the changes clearly implied by edit_request.
- Do NOT rewrite or reframe unrelated people; keep prior people objects unchanged unless the edit_request requires changes.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  user = (
    "Use the conversation and business context to finalize People & Capability.\n"
    "Business context (JSON):\n"
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
