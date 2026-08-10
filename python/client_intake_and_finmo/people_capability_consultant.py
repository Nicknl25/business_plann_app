from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
try:
  from openai_http import post_openai_with_retries  # type: ignore
except Exception:
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
FINALIZE_TOKEN = "[[FINALIZE_READY]]"
_RETRYABLE_STATUS = {429, 502, 503, 504}
REVIEW_TOKEN = "[[PEOPLE_REVIEW]]"


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


def _openai_timeout_seconds() -> Optional[int]:
  _load_root_env()
  return None


def _format_openai_error(resp: requests.Response) -> str:
  if resp.status_code in _RETRYABLE_STATUS:
    return "We're having trouble reaching our AI service right now. Please try again in a minute."
  return f"OpenAI API error {resp.status_code}: {resp.text[:500]}"


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  return post_openai_with_retries(
    url=url,
    headers=headers,
    payload=payload,
    timeout_seconds=timeout,
    retryable_status=_RETRYABLE_STATUS,
    max_attempts=3,
  )


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
              "annual_wage": {"type": ["number", "null"]},
              "wage_source": {"type": "string"},
            },
            "required": [
              "full_name",
              "role_title",
              "primary_responsibilities",
              "relevant_background",
              "experience_years",
              "why_strengthens_business",
              "paragraph",
              "annual_wage",
              "wage_source",
            ],
          },
        },
        "key_people_summary": {"type": "string"},
        "inferred_roles": {
          # No minItems: an operating business's inferred_roles are REQUIRED to be
          # empty (rest-of-team payroll is captured as one stated figure instead);
          # a schema-forced minimum would override that prompt rule every time.
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "role_title": {"type": "string"},
              "annual_wage": {"type": ["number", "null"]},
              "wage_source": {"type": "string"},
              "months_until_hire": {"type": ["number", "null"]},
              "notes": {"type": "string"},
            },
            "required": ["role_title", "annual_wage", "wage_source", "months_until_hire", "notes"],
          },
        },
        "inferred_roles_summary": {"type": "string"},
        "business_naics_6": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
      },
      "required": [
        "people",
        "key_people_summary",
        "inferred_roles",
        "inferred_roles_summary",
        "business_naics_6",
        "confidence",
      ],
    },
  }


def _progress_schema() -> Dict[str, Any]:
  return {
    "name": "people_collection_progress",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "people": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "full_name": {"type": "string"},
              "role_title": {"type": "string"},
              "relevant_background": {"type": "string"},
              "experience_years": {"type": "string"},
              "annual_wage": {"type": ["number", "null"]},
              "wage_source": {"type": "string"},
            },
            "required": [
              "full_name",
              "role_title",
              "relevant_background",
              "experience_years",
              "annual_wage",
              "wage_source",
            ],
          },
        },
        "confidence": {"type": "number"},
      },
      "required": ["people", "confidence"],
    },
  }


def extract_people_collection_progress(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  Backend-only structured extraction of raw People facts during collection.
  """
  api_key = _require_openai_key()
  model = _openai_model()
  schema_wrapper = _progress_schema()

  system = """
You are extracting structured People & Capability collection progress for backend persistence only.

Return ONLY JSON matching the provided schema.

Purpose:
- Maintain the current raw key-people facts captured so far during the People consult.
- This is not the final narrative output and not the inferred-roles step.

Rules:
- Use existing_people_capability_json from the context as the canonical baseline when present.
- Keep already captured people unless the conversation clearly changes or removes them.
- Output one object per currently confirmed key person in the conversation so far.
- Do not invent people.
- Do not output inferred roles.
- Do not output narrative paragraphs or summaries.
- relevant_background should be a concise factual phrase combining relevant experience, education, credentials, or licenses actually stated by the client.
- experience_years should be the best current textual value for years of relevant experience.
- annual_wage should stay null unless it is already present in the baseline context or clearly stated by the client.
- wage_source should be:
  - "client_override" if the client explicitly provided a wage
  - "gpt_estimate" only if the baseline already contains that source
  - "unknown" otherwise
- If the latest turn adds no new person facts, return the current baseline people list unchanged.
""".strip()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": "Current known People context (JSON):\n" + context_blob},
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

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
    raise RuntimeError("People progress extraction did not return a JSON object.")
  return parsed


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
- THE OWNER IS ALWAYS A KEY PERSON when they work in the business: capture them as a role with what they actually pay themselves (annual_wage). Owner pay lives HERE - the people section is its only home; no other section asks about it.
- A CREW OR GROUP IS NEVER A KEY PERSON (CW-024 #108): key-person rows are single named humans. When the client describes a crew, team, or group of interchangeable workers ("four crew at $34,000 each"), do NOT create a person row for them - their combined payroll belongs in the one rest-of-team total, and the client's per-head figures are how you compute it. One group, one home, or the same people end up counted twice.

Senior consultant lens (LIGHT plausibility checks; the final planning pass is the final arbitrator):
- Do quick, human plausibility checks while capturing people (titles, experience, and whether the person is actually involved today vs hypothetical).
- If something seems materially unclear/implausible (e.g., multiple executives listed but the business is clearly solo/pre-launch), ask ONE clarifying question and then proceed.
- Do not turn this into a deeper ops/financial audit; just capture best-current reality. Cross-domain reconciliation happens in the final planning pass.

Style requirements:
- Calm, human pacing.
- Ask one combined question at a time (do not split the same person into multiple back-to-back questions).
- One person at a time.
- No overwhelming lists.
- No HR advice, no hiring recommendations, no legal claims.
- No meta commentary: do NOT narrate your writing process or say things like "here's a professional way to say it", "I'll clean up the wording", "polished option", or similar.
- During the consult, do NOT show drafted paragraphs, inferred roles, partial write-ups, or preview summaries. Capture information quietly and save all writing for the controller-owned final review only.
- Do not ask the client to author content: never ask them to list responsibilities, background, strengths, bullet points, short phrases, or write narrative/justification.
- Do not refer to anything as a "section" and do not claim the wording will appear verbatim in a business plan. This is intake capture used later for plan generation.
- Use existing business context first (business model, delivery model, operating summary, pricing, and any prior people entries) to infer responsibilities and credibility signals before asking anything new.
- The context JSON may include shared_context with outputs from other consults; treat it as read-only facts and do not re-run other consults.

One-time nudge (use once early, then never repeat):
- Briefly mention that businesses often highlight a small number of pivotal roles (leadership, operations, technical/licensed, client-facing), but this is not a checklist.
- Also include one short stage-aware framing sentence so the client knows how to interpret later inferred roles and timing:
  - pre-revenue: frame later inferred roles as initial buildout capacity for launch and early operation.
  - early-stage: frame later inferred roles as additions that support ramp, increasing workload, and early specialization.
  - operating: frame later inferred roles as targeted additions or specialization within an already functioning business, not a rebuild from scratch.
- Keep that framing light: one sentence only, no extra question, no preview of specific roles, and no repeat after the early nudge.

Flow:
1) Single combined intake question per person (one question total for each person):
   - Ask for full name, title/role, years of relevant experience (numeric), and relevant education/credentials.
   - If education/credentials are unknown, the client can say "none".
2) Inference-first (internal only):
   - Based on the person's title and the business context, infer typical responsibilities and credibility signals.
   - Do NOT present per-person summaries during the consult.
3) Continue:
   - After the client provides details for a person, ask if they want to add another person before moving on.
   - Do NOT transition to the next consult (e.g., Financials) until the client explicitly says they are done adding people.
   - Do NOT generate any interim recap, consolidated summary, capability narrative, pre-review write-up, inferred roles preview, or approval request.
   - The final review is controller-owned and happens outside this turn function.
4) Role coverage:
   - Infer responsibilities and later support-role needs internally only.
   - Do NOT present inferred roles, timing, or wage ideas during collection.

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
- Do NOT emit {REVIEW_TOKEN} in this turn function.
- Do NOT emit {FINALIZE_TOKEN} in this turn function.
- Output only collection-stage conversational text: either a single combined intake question, a brief acknowledgement plus "add another person?" question, or a brief clarification question.
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
    raise RuntimeError(_format_openai_error(resp))

  text = _parse_responses_text(resp.json())
  text = text.replace(FINALIZE_TOKEN, "").replace(REVIEW_TOKEN, "").strip()
  return {"assistant_message": text, "finalize_ready": False, "review_ready": False}


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
- inferred_roles must be a short list (0-4) of additional roles likely needed in the first year based on the operating model, LOBs/products, capacity, and stage. For pre-revenue and early-stage businesses propose 1-4 roles; for operating businesses inferred_roles MUST be an empty list (see the business_stage rules below).
  - Do NOT include the already-listed key people in inferred_roles.
  - Each role must include a short "notes" explanation of why it is needed (plain language, 1 sentence).
  - Each role must include months_until_hire (number of months from now when the role would come online).
  - annual_wage can be null if unknown; if you estimate a number, set wage_source to "gpt_estimate".
  - If you cannot estimate, set annual_wage to null and wage_source to "unknown".
- STICKY CLIENT WAGES: for any person or role whose wage the CLIENT stated in conversation (or whose baseline entry carries wage_source "client_override"), preserve that annual_wage exactly and keep wage_source "client_override". A stated wage is a fact, never an estimate to regenerate - downstream wage defaults must not overwrite it.
- inferred_roles_summary must be a short paragraph summarizing the proposed roles (no wages), or an empty string when inferred_roles is empty.

Client-facing wording (STRICT):
- Never use the phrase "Year 1" or "Year-1" in messages to the client. Say it naturally instead: "the first year", "the year ahead", or "over the next year". Refer to inferred roles simply as "suggested roles".
- business_naics_6 can be null; do NOT guess it.
- Do NOT include meta phrases like "professional way to say this" or "I'll clean up wording" in the paragraph text.
- Do not refer to the output as a "section" and do not say it will appear verbatim in a plan; treat it as narrative source material.
- Fact-bearing template rule: if you mention the business name, use {{fact:business.name}} (do not print the literal name).
- business_stage from context is a required reasoning constraint for inferred roles, notes, timing, and summary:
  - If business_stage is pre-revenue:
    - inferred roles should reflect initial buildout and coverage of core functions needed to launch and stabilize early operation.
    - months_until_hire should reflect when those capabilities first become necessary, including immediate roles when needed for launch.
    - inferred_roles_summary should read like launch-readiness planning, not mature optimization.
  - If business_stage is early-stage:
    - inferred roles should reflect ramp, increasing workload, and early specialization as demand grows.
    - months_until_hire should reflect growth timing and early operational strain, not all roles front-loaded at once.
    - inferred_roles_summary should read like scaling and proving repeatability, not a business being built entirely from scratch.
  - If business_stage is operating (or missing/unknown):
    - inferred_roles MUST be an empty list and inferred_roles_summary an empty string. An operating business already has its team; the app separately captures one total payroll figure for everyone beyond the key people, so do NOT propose suggested roles and do NOT ask the client about team payroll yourself.

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
