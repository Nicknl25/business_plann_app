"""THE COHERENCE AUTHOR - step 3 (Nick 2026-09-12, approved build order).

"The agent thinks like a consultant. It has the transcript, the refusals,
the business, and the arithmetic. It decides what this business should
consider. The engine tells it what each one does and refuses the ones that
aren't allowed."

Discipline (the same one that made the writing phase work):
  THE AGENT PROPOSES, THE ENGINE PRICES. The agent returns structured
  candidates - a lever and a depth, or a line and a multiplier - with a
  plain label and why. It asserts no numbers: a dollar figure in its
  wording is replaced by the engine's own. Every impact is computed by
  controller.price_cost_candidate / price_revenue_candidate, never stated
  by the model.
  A SELECTED OPTION IS APPLIED BY CODE AGAINST A NAMED LEVER. The agent's
  candidates become options with the same patch specs as before; a click
  sends the id; the section applies the stored spec.
  FLOORS ARE READ BEFORE GENERATION. The agent returns floors_read - the
  refusals it finds in the client's own words - and the section records
  them as client floors BEFORE the engine builds the available moves, so
  a refused lever is never generated.

GPT, through the same locked path as every other intake call (recorded
and replayed by the response lock; the persona gate stays deterministic).
Nick: "GPT unless you can show me it can't do the job."
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_RETRYABLE = (408, 409, 425, 429, 500, 502, 503, 504)
TIMEOUT_SECONDS = 120.0
MAX_TRANSCRIPT_MESSAGES = 90
MAX_CANDIDATES = 8

COST_LEVERS = ("gna", "cogs", "rent", "marketing", "owner_draw", "hire_timing")
FLOOR_KINDS = ("rent", "payroll", "marketing", "gna", "cogs", "pricing", "volume", "new_lines", "cost_structure")
# what the owner's words were: only a refusal or a commitment that cannot
# move is recorded as a floor; a cost merely mentioned is not (the proof over
# Castellane read "rent and the plant lease come to 78,000 a month" as a floor)
FLOOR_READ_KINDS = ("refused", "cannot_move", "mentioned")
BINDING_FLOOR_READ_KINDS = ("refused", "cannot_move")

SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "floors_read": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "cost": {"type": "string", "enum": list(FLOOR_KINDS)},
          "because": {"type": "string"},
          "kind": {"type": "string", "enum": list(FLOOR_READ_KINDS)},
        },
        "required": ["cost", "because", "kind"],
      },
    },
    "candidates": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "kind": {"type": "string", "enum": ["cost", "price", "volume"]},
          "levers": {"type": "array", "items": {"type": "string", "enum": list(COST_LEVERS)}},
          "depth": {"type": "number"},
          "line_moves": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": False,
              "properties": {"line": {"type": "string"}, "multiplier": {"type": "number"}},
              "required": ["line", "multiplier"],
            },
          },
          "label": {"type": "string"},
          "why": {"type": "string"},
        },
        "required": ["kind", "levers", "depth", "line_moves", "label", "why"],
      },
    },
  },
  "required": ["floors_read", "candidates"],
}

SYSTEM = (
  "You are the consultant sitting with the owner of a small business at the end of their planning intake. "
  "Their plan does not yet work on paper: a mature quarter comes up short of what a lender needs to see. Your job is to "
  "decide what THIS business should consider to close that gap, and to say each option in the owner's own language.\n\n"
  "You are given the transcript so far (read it - the owner has told you what is fixed and what can move), the "
  "business, the gap, the cost levers that exist for this business (each with where it is today and how far the "
  "engine judges it could go), the revenue lines (each with today's price and units and how far the market is judged "
  "to allow), the refusals already recorded, and any options the owner already declined.\n\n"
  "Return two things.\n"
  "1. floors_read: every cost or lever the owner has ruled out in their own words - a signed lease means rent; "
  "'leave the crews alone' or 'we are at what we can staff' means payroll; 'no more volume' means volume; 'no more "
  "price changes' or 'those are contracted' means pricing; 'I don't want either of those lines' means new_lines. "
  "Quote the owner in `because` and classify it in `kind`: 'refused' when the owner declined to move it ('leave the "
  "team alone', 'no more volume', 'no to both'), 'cannot_move' when it is a commitment that cannot move ('the lease is "
  "signed', 'those prices are contracted'), and 'mentioned' when the owner only described the cost ('we rent the plant', "
  "'rent and the lease come to 78,000 a month', 'we have four crews'). Needing a thing is not a floor on its cost: 'we will "
  "always need the cleanroom' or 'we rent the plant' says the business needs a space, not that a cheaper or smaller one is "
  "out of the question - that is 'mentioned'. Likewise, saying the business does not offer something today "
  "('no, just recurring office cleaning', 'we don't do carpets') describes the business and is NOT a refusal to "
  "add a line later - 'mentioned', never new_lines. Only 'refused' and 'cannot_move' become floors; "
  "'mentioned' is kept for the record and holds nothing. Never list a floor the owner did not state, and when in doubt "
  "classify it 'mentioned'.\n"
  "2. candidates: three to eight moves you would actually put in front of this owner, most useful first. A candidate "
  "is a cost move (levers + depth, where depth is the fraction of the way from today to the judged floor: 0.25 is "
  "gentle, 0.5 is halfway, 1.0 is all the way) or a price or volume move (line_moves: a multiplier per line, 1.0 "
  "leaves a line alone; never above the line's believable maximum). Combine levers when that is what a consultant "
  "would suggest. Never propose a lever or a line the owner refused, never a candidate they already declined, and "
  "never a depth or multiplier the bounds do not allow - the engine will refuse it, and a refused candidate helps "
  "no one.\n\n"
  "Wording: label is a short plain-language name (under twelve words); why is one sentence in the owner's own terms "
  "about what changes and what stays as it is - 'pay less for materials: your suppliers would need to come down a "
  "little' - NEVER a dollar figure or a percentage. The engine attaches every number. Do not mention lever ids, "
  "floors, bounds, or the engine."
)


def _model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _key() -> Optional[str]:
  k = (os.getenv("OPENAI_API_KEY") or "").strip()
  return k or None


_FIGURE_RE = re.compile(r"\$\s?\d|\d[\d,]*\.?\d*\s?%|\b\d{1,3}(?:,\d{3})+\b|\b\d{4,}\b")


def wording_has_a_number(text: str) -> bool:
  """The agent asserts no numbers. A dollar sign, a percent, a thousands
  figure or any four-plus-digit number in its wording means the engine's
  own wording is used instead."""
  return bool(_FIGURE_RE.search(str(text or "")))


def build_payload(
  *,
  transcript: List[Dict[str, str]],
  business: Dict[str, Any],
  gap_display: str,
  cost_levers: List[Dict[str, Any]],
  lines: List[Dict[str, Any]],
  floors_recorded: Dict[str, Any],
  declined: List[str],
  rounds_done: List[str],
) -> Dict[str, Any]:
  tail = transcript[-MAX_TRANSCRIPT_MESSAGES:]
  user_payload = {
    "business": business,
    "gap_per_quarter": gap_display,
    "transcript": [{"role": m.get("role"), "content": str(m.get("content") or "")[:1500]} for m in tail],
    "cost_levers_available": cost_levers,
    "revenue_lines": lines,
    "refusals_already_recorded": floors_recorded,
    "candidates_already_declined": declined,
    "lever_families_already_walked": rounds_done,
  }
  return {
    "model": _model(),
    "input": [
      {"role": "system", "content": SYSTEM},
      {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
    ],
    "text": {"format": {"type": "json_schema", "name": "coherence_author", "schema": SCHEMA, "strict": True}},
    "store": False,
  }


def _parse(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  for item in data.get("output") or []:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
      if part.get("type") == "output_text" and part.get("text"):
        try:
          parsed = json.loads(part["text"])
          if isinstance(parsed, dict):
            return parsed
        except Exception:
          continue
  return None


def author(*, payload: Dict[str, Any], post=None) -> Optional[Dict[str, Any]]:
  """One locked GPT call. Returns {"floors_read": [...], "candidates": [...]}
  or None when the call cannot be made or the reply does not parse - the
  section then falls back to the legacy planner and records why."""
  key = _key()
  if not key:
    return None
  if post is None:
    from client_intake_and_finmo.openai_http import post_openai_with_retries as post  # type: ignore
  try:
    resp = post(url=OPENAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload=payload, timeout_seconds=TIMEOUT_SECONDS, retryable_status=_RETRYABLE, max_attempts=2)
    if resp.status_code >= 400:
      return None
    parsed = _parse(resp.json())
  except Exception:
    return None
  if not isinstance(parsed, dict):
    return None
  read = [f for f in (parsed.get("floors_read") or []) if isinstance(f, dict) and f.get("cost") in FLOOR_KINDS]
  floors = [f for f in read if f.get("kind") in BINDING_FLOOR_READ_KINDS]
  mentioned = [f for f in read if f.get("kind") not in BINDING_FLOOR_READ_KINDS]
  cands = [c for c in (parsed.get("candidates") or []) if isinstance(c, dict) and c.get("kind") in ("cost", "price", "volume")]
  return {"floors_read": floors, "floors_mentioned": mentioned, "candidates": cands[:MAX_CANDIDATES]}
