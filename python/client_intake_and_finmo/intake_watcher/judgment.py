"""The model read - GPT, through the same locked path as every other intake
call (recorded and replayed by the response lock; the persona gate stays
deterministic). It reads the transcript and the turn's store diff and
files observations under the vocabulary's MODEL kinds, with the client's
words quoted as evidence. It asserts no numbers of its own: every stored
value it cites comes from the diff it was shown.

Nick: "GPT unless you can show me it can't do the job."
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.intake_watcher.vocabulary import MODEL_KINDS, observation

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_RETRYABLE = (408, 409, 425, 429, 500, 502, 503, 504)
TIMEOUT_SECONDS = 90.0
MAX_TRANSCRIPT_MESSAGES = 80

SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "observations": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "kind": {"type": "string", "enum": list(MODEL_KINDS)},
          "client_words": {"type": "string"},
          "field": {"type": "string"},
          "stored_value": {"type": "string"},
          "expected": {"type": "string"},
          "why": {"type": "string"},
        },
        "required": ["kind", "client_words", "field", "stored_value", "expected", "why"],
      },
    }
  },
  "required": ["observations"],
}

SYSTEM = (
  "You are a silent observer of a business-plan intake conversation. You never speak to the client and you "
  "never change anything. Your only job is to NOTICE when the app's behaviour or the stored data disagrees "
  "with what the client actually said, and to file an observation with evidence.\n\n"
  "You are shown the transcript so far, the latest exchange, the fields that changed in the store on this "
  "turn (before -> after), the costs and levers the client has refused, and the coherence options on offer if any.\n\n"
  "File an observation ONLY for these kinds:\n"
  "- refusal_violated: the client said a cost or lever cannot move (a signed lease, leave the crews alone, no more "
  "volume, no more price changes, leave that line alone) and this turn's diff moved it, or the app offered to move it.\n"
  "- correction_ignored: the client restated a figure or a correction they had already given, and the diff shows "
  "nothing moved for it.\n"
  "- figure_misread: the app's reply or the diff carries a number the client did not say (for example the client "
  "wrote 'nine hundred thousand' and the app took 900, or the client quoted the app's own number back and the app "
  "treated it as a new fact).\n"
  "- unstated_figure_in_basis: the diff adds a wage, a role, a cost, or a revenue figure that no one in the "
  "transcript stated.\n"
  "- lever_moved_stated_figure: a stored figure the client stated moved because of an app lever without the client "
  "saying yes to that specific change.\n"
  "- intent_unmet: the client asked to stop, pause, skip, move on, wrap up, or finish, and the reply did something else.\n"
  "- question_unanswered: the client asked a direct question and the reply did not answer it.\n\n"
  "Rules: quote the client's exact words in client_words. Put the stored figure from the diff in stored_value and "
  "what the client's words imply in expected, as text; never invent a number that is not in the transcript or the "
  "diff. If nothing is wrong, return an empty list. Do not file style complaints. Do not file what you cannot "
  "evidence from the transcript or the diff."
)


def _model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _key() -> Optional[str]:
  k = (os.getenv("OPENAI_API_KEY") or "").strip()
  return k or None


def build_payload(*, transcript: List[Dict[str, str]], user_text: str, assistant_text: str,
                  diff: Dict[str, Any], floors: Dict[str, Any], options: List[Dict[str, Any]]) -> Dict[str, Any]:
  tail = transcript[-MAX_TRANSCRIPT_MESSAGES:]
  user_payload = {
    "transcript": [{"role": m.get("role"), "content": str(m.get("content") or "")[:1500]} for m in tail],
    "latest_exchange": {"client": user_text, "app": assistant_text},
    "store_diff_this_turn": diff,
    "client_refusals_recorded": floors,
    "coherence_options_on_offer": [
      {"id": o.get("id"), "label": o.get("label"), "closes": o.get("closes_display")} for o in (options or [])
      if isinstance(o, dict)
    ],
  }
  return {
    "model": _model(),
    "input": [
      {"role": "system", "content": SYSTEM},
      {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
    ],
    "text": {"format": {"type": "json_schema", "name": "intake_watch_observations", "schema": SCHEMA, "strict": True}},
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


def judge_turn(*, draft_id: str, turn: int, transcript: List[Dict[str, str]], user_text: str, assistant_text: str,
               diff: Dict[str, Any], floors: Dict[str, Any], options: List[Dict[str, Any]],
               post=None) -> List[Dict[str, Any]]:
  """One locked GPT call. Returns observation records (possibly empty). A
  transport failure returns a single 'watcher_model_unavailable' record so
  silence is never mistaken for a clean turn."""
  key = _key()
  if not key:
    return [{"kind": "watcher_model_unavailable", "severity": "minor", "detector": "model", "draft_id": draft_id,
             "turn": turn, "field": "", "client_words": "", "stored_value": None, "expected": None,
             "why": "OPENAI_API_KEY unset"}]
  payload = build_payload(transcript=transcript, user_text=user_text, assistant_text=assistant_text,
                          diff=diff, floors=floors, options=options)
  if post is None:
    from client_intake_and_finmo.openai_http import post_openai_with_retries as post  # type: ignore
  try:
    resp = post(url=OPENAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload=payload, timeout_seconds=TIMEOUT_SECONDS, retryable_status=_RETRYABLE, max_attempts=2)
    if resp.status_code >= 400:
      raise RuntimeError(f"http {resp.status_code}: {str(getattr(resp, 'text', ''))[:200]}")
    parsed = _parse(resp.json()) or {}
  except Exception as exc:
    return [{"kind": "watcher_model_unavailable", "severity": "minor", "detector": "model", "draft_id": draft_id,
             "turn": turn, "field": "", "client_words": "", "stored_value": None, "expected": None,
             "why": f"{type(exc).__name__}: {str(exc)[:300]}"}]
  out: List[Dict[str, Any]] = []
  for o in parsed.get("observations") or []:
    if not isinstance(o, dict) or o.get("kind") not in MODEL_KINDS:
      continue
    out.append(observation(str(o["kind"]), draft_id=draft_id, turn=turn, client_words=str(o.get("client_words") or ""),
                           stored_value=o.get("stored_value"), expected=o.get("expected"), why=str(o.get("why") or ""),
                           field=str(o.get("field") or ""), detector="model"))
  return out
