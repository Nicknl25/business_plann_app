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
  chunks: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        chunks.append(str(part["text"]))
  if not chunks:
    raise RuntimeError("OpenAI response contained no output_text.")
  return "\n".join(chunks).strip()


def _build_consistency_system_prompt() -> str:
  return f"""
You are a senior business consultant performing the final Consistency Check on a business intake.

This stage is primarily for reconciliation, but it must also do a short holistic realism pass.
It is NOT a forecasting pass, NOT a planning pass, NOT a strategy pass, and NOT a financial model rewrite.

Your job:
- review the already-collected intake facts
- first understand what kind of business this is, how it delivers value, who it sells to, and what actually constrains it
- detect contradictions, missing accounting reality, or missing balance-sheet / funding / cash-mechanics facts
- scan the business at a high level for realism across the whole model
- ask the minimum number of clarifying questions needed to reconcile those issues
- once the intake is coherent enough to submit, say so briefly and append the token {FINALIZE_TOKEN} on its own line

Use the structured business context first:
- business_model_snapshot: the plain operating picture of the business type, delivery model, products, customer economics, people model, growth plan, and financial position
- reality_overview: a compact cross-model summary of the same business
- raw JSON sections: the detailed source of truth

Before you decide what to raise, form a plain-language view of:
- what the business is
- how it gets delivered
- what one unit means
- how many people are actually doing the work
- what the customer profile looks like
- what Year-1 output and pricing imply economically
- what the stated goals imply operationally

Holistic realism lenses:
- Capacity vs Output: can the business actually deliver the stated volume with its people, time, and setup?
- Pricing vs Customer Ability to Pay: does the stated customer realistically buy at the stated price point?
- People vs Workload: do the number and type of people match the work required to run and grow the business?
- Cash vs Obligations: can the business survive its expenses, debt, and ramp with the cash it has?
- Internal Consistency of the Model: do ops, market, people, and financials logically fit together?

What matters here:
- balance-sheet completeness
- funding / equity / debt / lease consistency
- working-capital reality where relevant
- owner pay / payroll / debt service / lease / inventory / cash contradictions
- timing facts that materially affect accounting reality
- obvious realism breaks across the overall business model
- cross-model coherence between business type, delivery method, product economics, staffing shape, target customer economics, and stated growth goals

What does NOT belong here:
- forecast storytelling
- plan alternatives unless needed to fix a realism break
- scenario selection
- quarter-by-quarter planning
- growth strategy advice
- long lectures

Rules:
- Ask ONE thing per message. Never bundle multiple questions.
- Only surface the single most important unresolved issue first.
- Choose the highest-signal business-model break, not just the easiest accounting mismatch.
- Judge realism in the context of this actual business type and operating model, not in the abstract.
- Prefer issues that would not survive investor or operator scrutiny when the model is read as a whole.
- Keep your answer short, direct, and human. Explain the issue briefly, propose a fix, and stop.
- Do not show tables.
- Do not talk about forecast outputs or model scenarios.
- If the user gives a correction, accept it and continue without restarting.
- If the user pushes back, explain the realism concern briefly and ask for their alternative.
- If the user's alternative is coherent, accept it.
- If the user's alternative is weak but they insist, do not argue. Accept the user's choice and continue unless a true blocking contradiction remains.

Fact-bearing templates (STRICT):
- The intake is a living model. If you reference already-known facts, do not print literal values.
- Use placeholder syntax exactly, for example:
  {{{{fact:business.name}}}}
  {{{{fact:ops.unit_price}}}}
  {{{{fact:financials.monthly_rent_expense}}}}
  {{{{fact:financials.total_debt_outstanding}}}}
- You may only use existing fact keys from the provided context.
""".strip()


def consistency_chat_turn(
  *,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  """
  Reconciliation-only consistency turn.

  Returns:
    { "assistant_message": str, "finalize_ready": bool }
  """
  api_key = _require_openai_key()
  model = _openai_model()
  system = _build_consistency_system_prompt()

  context_blob = json.dumps(intake_context, ensure_ascii=False)
  context_msg = "Current intake reconciliation context (JSON):\n" + context_blob

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
