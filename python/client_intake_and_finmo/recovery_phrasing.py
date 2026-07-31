"""Natural-language recovery phrasing — the cure for the bluntness class.

The disease (CW-003, issues equity/debt clarifiers + the "Continue."
shrug): when an answer fails a deterministic check, intake discarded the
model's natural message and surfaced a canned string ("What initial
equity amount should I record?"). The GPT must recover like a human
("Sorry — I don't think I caught that. Roughly how much have you put in
as your own equity?").

Division of labor (locked by design):
- WHICH fact is being asked stays FRAME-DECLARED and deterministic — the
  closed question passed in defines the semantics; this module may never
  add topics, numbers, or content.
- HOW it is asked is one bounded GPT call (through the shared locked
  HTTP layer, so identical situations replay deterministically).
- The deterministic string is ALWAYS the last-resort fallback: any
  failure here returns it verbatim. Reliability never regresses below
  the pre-fix behavior.

Deliberately NOT routed through here (Nick's ruling): closed-choice
menus (cash strategy), "Got it." acks, honest system-state messages
(hold / park / submit / run-complete), and the issue-#23 unapplied-
fields note — determinism there IS the honesty.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_URL = "https://api.openai.com/v1/responses"

_SYSTEM = (
  "You are the warm, plain-spoken voice of a business-planning consultant "
  "recovering from a small conversational stumble. The client's last message "
  "did not answer the question the app needs, or the app has no prepared "
  "line for this moment. Write EXACTLY ONE short, natural, friendly sentence "
  "(two at most) that accomplishes the TASK below. Rules: never add new "
  "topics, numbers, examples, or explanations; never mention internal field "
  "names, formats, or systems; never scold; a brief, human acknowledgement "
  "like \"Sorry - I don't think I caught that\" is welcome when the client "
  "just said something that didn't answer the question. Output only the "
  "sentence itself."
)


def _model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def naturalize_recovery(
  *,
  closed_question: str,
  user_message: str = "",
  fallback: Optional[str] = None,
) -> str:
  """One natural sentence accomplishing exactly ``closed_question``'s ask.

  ``closed_question`` is the deterministic, frame-declared statement of
  WHAT must be asked (a stage clarifier, a format prompt's semantics, or
  a continuation instruction). Any failure returns ``fallback`` (default:
  the closed question itself) — the canned string never disappears, it
  just stops being the first choice.
  """
  safe_fallback = (fallback if fallback is not None else closed_question) or ""
  try:
    from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore

    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
      return safe_fallback
    task = f"TASK - ask the client this, in your own words: {closed_question}"
    if user_message.strip():
      task += f"\nThe client's last message was: {user_message.strip()[:400]}"
    resp = post_openai_with_retries(
      url=_URL,
      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
      payload={
        "model": _model(),
        "instructions": _SYSTEM,
        "input": task,
        "max_output_tokens": 4000,
      },
      timeout_seconds=30,
      retryable_status={429, 502, 503, 504},
      max_attempts=2,
    )
    if int(getattr(resp, "status_code", 0) or 0) != 200:
      return safe_fallback
    data = resp.json()
    chunks = []
    for item in data.get("output") or []:
      for part in item.get("content") or []:
        if part.get("type") == "output_text" and part.get("text"):
          chunks.append(str(part["text"]))
    text = " ".join(" ".join(chunks).split()).strip()
    if not text or len(text) > 400:
      return safe_fallback
    return text
  except Exception as exc:  # noqa: BLE001 — recovery must never break a turn
    logger.debug("naturalize_recovery_fallback: %s", type(exc).__name__)
    return safe_fallback


def continuation_nudge(*, focus: str = "") -> str:
  """Natural replacement for the literal \"Continue.\" shrug: one short
  line inviting the client to carry on. Fallback stays \"Continue.\"."""
  where = f" They are currently in the {focus} part of the intake." if focus else ""
  return naturalize_recovery(
    closed_question=(
      "There is no specific question pending - write one short, friendly line "
      f"inviting the client to pick up right where the conversation left off.{where}"
    ),
    fallback="Continue.",
  )
