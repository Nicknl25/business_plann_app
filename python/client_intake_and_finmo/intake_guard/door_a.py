"""DOOR A - the patch, before it lands.

The router proposed a patch from the client's latest message. The guard
reads the client's words, the conversation, the store as it stands and
the proposed patch, and returns the patch it allows: the same, rewritten
(a value moved to the field the client named, or restored to what they
said), or with a field held back behind a question when the right home is
genuinely ambiguous. A rewrite carries its receipt in the client's own
language and the words that carry the figure. It never invents a number.

Provenance, not inference: keys the client's pick produces in the walk
(coherence.option, coherence.assert_floor, coherence.parked,
ops.product_overrides) are the client's choices - door A validates the
option ID against the client's words and the options that were offered,
and never touches the writes an option produces (the engine computes
those from the priced option).

Fail OPEN on a timeout, logged loudly (Nick: a stalled intake is worse
than an unguarded turn).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_RETRYABLE = (408, 409, 425, 429, 500, 502, 503, 504)
DEADLINE_SECONDS = float(os.getenv("INTAKE_GUARD_DEADLINE_SECONDS") or 28.0)
MAX_TRANSCRIPT_MESSAGES = 30

# the walk's own doors: the client's choice by id, validated, never rewritten field by field
WALK_KEYS = ("coherence.option", "coherence.assert_floor", "coherence.parked", "coherence.retention_answer",
             "ops.product_overrides", "option", "assert_floor", "parked", "retention_answer")


def _model() -> str:
  return (os.getenv("INTAKE_GUARD_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _key() -> Optional[str]:
  k = (os.getenv("OPENAI_API_KEY") or "").strip()
  return k or None


def enabled() -> bool:
  return (os.getenv("INTAKE_GUARD_ENABLED") or "1").strip().lower() not in ("0", "false", "no", "off")


SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "allowed": {
      "type": "array",
      "description": "every key of the patch you allow, with its value as JSON text",
      "items": {
        "type": "object", "additionalProperties": False,
        "properties": {"key": {"type": "string"}, "value_json": {"type": "string"}},
        "required": ["key", "value_json"],
      },
    },
    "rewrites": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
          "from_key": {"type": "string"},
          "to_key": {"type": "string"},
          "value_json": {"type": "string"},
          "client_words": {"type": "string"},
          "receipt": {"type": "string"},
          "why": {"type": "string"},
        },
        "required": ["from_key", "to_key", "value_json", "client_words", "receipt", "why"],
      },
    },
    "asks": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
          "key": {"type": "string"},
          "client_words": {"type": "string"},
          "question": {"type": "string"},
          "why": {"type": "string"},
        },
        "required": ["key", "client_words", "question", "why"],
      },
    },
    "hold_cleared": {"type": "boolean"},
  },
  "required": ["allowed", "rewrites", "asks", "hold_cleared"],
}

SYSTEM = (
  "You sit between the consultant's router and the store of a small-business planning intake. The router just "
  "proposed a PATCH (field -> value) from the client's latest message. Your job is to make sure every value goes "
  "where the client actually put it, before it is written.\n\n"
  "Return `allowed`: the patch you allow - every key you keep, with its value as JSON text (numbers unquoted, "
  "strings quoted, objects/arrays as JSON). Leave a key out to drop it. Three moves are yours:\n"
  "1. ALLOW: the value is what the client said, on the field they meant. Most keys.\n"
  "2. REWRITE (in `rewrites`, and reflected in `allowed`): the client stated this figure for a DIFFERENT thing - "
  "'$2,400 a month for the three vans, inside the other bills' proposed as monthly rent is a rewrite: drop the "
  "rent key (rent stays what they said before) and, if a field for what they meant exists among the keys or the "
  "store, put it there; or the router restated a figure the client already gave differently - restore theirs. "
  "Every rewrite carries `client_words` (quote the client) and a one-sentence `receipt` in the client's own "
  "language that the consultant will say back: 'You told me the $2,400 is the van lease inside your other bills, "
  "so I've left rent at $2,600.' Never 'corrected by the guard'.\n"
  "3. ASK (in `asks`, and the key left out of `allowed`): the right home for the figure is GENUINELY ambiguous "
  "from their words. Give the question you would ask, plainly. Ask only when you cannot tell; a van lease "
  "payment sitting in rent is not ambiguous.\n\n"
  "Rules that bind you: you NEVER invent a number - a value may only be one the client stated in this "
  "conversation, and `client_words` must carry it. You never touch a value because a benchmark disagrees with it "
  "- the client's stated cost is a fact. Keys that begin with 'coherence.' or 'ops.product_overrides' are the "
  "client's choices in the planning walk: `coherence.option` names an option by id from the list the "
  "consultant offered - check that the id matches the option the client's words point to ('Option 1' is the "
  "first offered; 'the overhead one' is the option whose label says overhead) and rewrite the id if not; never "
  "rewrite anything else under those keys. When unsure, ALLOW - an unguarded write is the consultant's error to "
  "own; a wrong rewrite is yours.\n"
  "If a `hold` is shown (a question you asked on an earlier turn about a field), set `hold_cleared` true when "
  "the client's latest message answers it (and put the answered value in `allowed` under that key if it is in "
  "the patch), false otherwise."
)


_ZERO_WORDS_RE = re.compile(r"(?<![\d.,])0(?![\d.,%])|\b(zero|none|nothing|nil|no|not any|not yet|nobody|free|n/?a)\b|\$0\b", re.I)


def _is_zero(value: Any) -> bool:
  if value is True or value is False:
    return False
  try:
    return abs(float(value)) < 1e-9
  except (TypeError, ValueError):
    return False


def drop_unsaid_zeros(patch: Dict[str, Any], user_text: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  """A ZERO THE CLIENT DID NOT SAY IS NOT A VALUE (2026-09-12, the issue-578
  class): the router answered a utilization question with a line row carrying
  unit_price = 0.0 - a placeholder, not a fact. A stated-fact leaf written as
  zero when the client's words carry no zero, none, no or nothing is dropped
  here, deterministically, before and regardless of the model. Returns the
  patch without them and the list of what was dropped."""
  from client_intake_and_finmo.intake_guard.provenance import is_stated_fact
  words = str(user_text or "")
  if _ZERO_WORDS_RE.search(words):
    return dict(patch or {}), []
  kept: Dict[str, Any] = {}
  dropped: List[Dict[str, Any]] = []
  for k, v in (patch or {}).items():
    key = str(k)
    if is_stated_fact(key) and _is_zero(v):
      dropped.append({"key": key, "value": v, "client_words": words,
                      "why": "a zero the client did not say is not a value - the question in view was not this field"})
      continue
    kept[key] = v
  return kept, dropped


@dataclass
class Verdict:
  patch: Dict[str, Any]
  rewrites: List[Dict[str, Any]] = field(default_factory=list)
  asks: List[Dict[str, Any]] = field(default_factory=list)
  dropped: List[Dict[str, Any]] = field(default_factory=list)
  hold_cleared: bool = False
  ran: bool = False
  timed_out: bool = False
  error: str = ""
  elapsed_ms: int = 0

  @property
  def receipts(self) -> List[str]:
    return [str(r.get("receipt") or "").strip() for r in self.rewrites if str(r.get("receipt") or "").strip()]

  @property
  def questions(self) -> List[str]:
    return [str(a.get("question") or "").strip() for a in self.asks if str(a.get("question") or "").strip()]

  @property
  def changed(self) -> bool:
    return bool(self.rewrites or self.asks or self.dropped)


def _store_slice(store: Dict[str, Any]) -> Dict[str, Any]:
  """What the guard needs of the store: the stated financials, the ops
  lines, the people rows - never private keys."""
  fin = {k: v for k, v in ((store.get("financials") or {}).items()) if not str(k).startswith("_")}
  ops = store.get("ops") or {}
  lines = []
  for lob in ops.get("lob_models") or []:
    if isinstance(lob, dict):
      for p in lob.get("products") or []:
        if isinstance(p, dict):
          lines.append({k: p.get(k) for k in ("product_name", "unit_price", "units_per_period_capacity",
                                             "units_per_week_capacity", "utilization_rate", "operating_periods_per_year")})
  people = [{k: p.get(k) for k in ("full_name", "role_title", "annual_wage")}
            for p in ((store.get("people") or {}).get("people") or []) if isinstance(p, dict)]
  return {"financials": fin, "lines": lines, "people": people,
          "rest_of_team_payroll_year1": (store.get("people") or {}).get("rest_of_team_payroll_year1")}


def _offered_options(messages: List[Dict[str, Any]], store: Dict[str, Any]) -> List[Dict[str, Any]]:
  st = ((store.get("financials") or {}).get("_coherence")) or {}
  rnd = st.get("round") or {}
  return [{"id": o.get("id"), "label": o.get("label")} for o in (rnd.get("options") or []) if isinstance(o, dict)]


def build_payload(*, patch: Dict[str, Any], user_text: str, messages: List[Dict[str, Any]], store: Dict[str, Any],
                  focus: str, hold: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  body = {
    "focus": focus,
    "client_latest_message": user_text,
    "transcript_tail": [{"role": m.get("role"), "content": str(m.get("content") or "")[:900]}
                        for m in messages[-MAX_TRANSCRIPT_MESSAGES:]],
    "proposed_patch": {k: v for k, v in patch.items()},
    "store": _store_slice(store),
    "options_offered_this_turn": _offered_options(messages, store),
    "hold": hold or None,
  }
  return {
    "model": _model(),
    "input": [{"role": "system", "content": SYSTEM},
              {"role": "user", "content": json.dumps(body, ensure_ascii=False, default=str)}],
    "text": {"format": {"type": "json_schema", "name": "intake_guard_door_a", "schema": SCHEMA, "strict": True}},
    "store": False,
  }


def _parse(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  for item in data.get("output") or []:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
      if part.get("type") == "output_text" and part.get("text"):
        try:
          j = json.loads(part["text"])
          if isinstance(j, dict):
            return j
        except Exception:
          continue
  return None


def _vj(s: Any) -> Any:
  try:
    return json.loads(s) if isinstance(s, str) else s
  except Exception:
    return s


_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")


def _value_in_words(value: Any, words: str) -> bool:
  """A rewritten NUMBER must appear in the client's quoted words (in any
  common basis: as stated, per month, per year, per quarter)."""
  try:
    v = float(value)
  except (TypeError, ValueError):
    return True   # not a number: a label or a choice
  found = []
  for m in _NUM_RE.finditer(str(words or "")):
    try:
      found.append(float(m.group(0).replace(",", "")))
    except ValueError:
      pass
  for f in found:
    for e in (f, f * 12, f / 12, f * 4, f / 4, f * 1000, f * 1_000_000):
      if abs(e - v) <= max(0.5, abs(v) * 0.005):
        return True
  return False


def review(*, patch: Dict[str, Any], user_text: str, messages: List[Dict[str, Any]], store: Dict[str, Any],
           focus: str = "", hold: Optional[Dict[str, Any]] = None, post=None) -> Verdict:
  """The door. Returns the allowed patch and what changed. Fail open."""
  original = dict(patch or {})
  if not enabled() or not original:
    return Verdict(patch=original)
  # the deterministic rule runs first and on every path, fail-open included
  original, dropped = drop_unsaid_zeros(original, user_text)
  for d in dropped:
    logger.error("INTAKE_GUARD_A_DROPPED_UNSAID_ZERO %s=%r words=%r", d["key"], d["value"], str(user_text or "")[:120])
  if not original:
    return Verdict(patch=original, dropped=dropped)
  key = _key()
  if not key:
    logger.error("INTAKE_GUARD_A_NO_KEY - the turn proceeds unguarded")
    return Verdict(patch=original, dropped=dropped, error="no_api_key")
  if post is None:
    from client_intake_and_finmo.openai_http import post_openai_with_retries as post  # type: ignore
  t0 = time.monotonic()
  try:
    resp = post(url=OPENAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload=build_payload(patch=original, user_text=user_text, messages=messages, store=store,
                                      focus=focus, hold=hold),
                timeout_seconds=DEADLINE_SECONDS, retryable_status=_RETRYABLE, max_attempts=1)
    if resp.status_code >= 400:
      logger.error("INTAKE_GUARD_A_HTTP_%s - the turn proceeds unguarded: %s", resp.status_code, str(resp.text)[:300])
      return Verdict(patch=original, dropped=dropped, ran=True, error=f"http_{resp.status_code}",
                     elapsed_ms=int((time.monotonic() - t0) * 1000))
    parsed = _parse(resp.json())
  except Exception as exc:  # noqa: BLE001 - FAIL OPEN, LOUDLY
    logger.error("INTAKE_GUARD_A_TIMEOUT_OR_ERROR after %.1fs - the turn proceeds unguarded: %s: %s",
                 time.monotonic() - t0, type(exc).__name__, exc)
    return Verdict(patch=original, dropped=dropped, ran=True, timed_out=True, error=f"{type(exc).__name__}: {exc}"[:300],
                   elapsed_ms=int((time.monotonic() - t0) * 1000))
  elapsed = int((time.monotonic() - t0) * 1000)
  if not isinstance(parsed, dict):
    logger.error("INTAKE_GUARD_A_UNPARSED - the turn proceeds unguarded")
    return Verdict(patch=original, dropped=dropped, ran=True, error="unparsed", elapsed_ms=elapsed)

  # AN OMISSION CHANGES NOTHING (stated_total, guarded default pass): the
  # model left a correctly-placed text field out of `allowed` and the key
  # was dropped, so the app asked the question again. The router's patch
  # stands; only a NAMED rewrite or a NAMED ask may change it, and `allowed`
  # is read only for a corrected option id.
  allowed_ids: Dict[str, Any] = {}
  for e in parsed.get("allowed") or []:
    if isinstance(e, dict) and e.get("key") in ("coherence.option", "option"):
      allowed_ids[str(e["key"])] = _vj(e.get("value_json"))
  final: Dict[str, Any] = dict(original)
  fin_store = (store or {}).get("financials") or {}
  rewrites: List[Dict[str, Any]] = []
  for r in parsed.get("rewrites") or []:
    if not isinstance(r, dict):
      continue
    fk, tk = str(r.get("from_key") or ""), str(r.get("to_key") or "")
    val = _vj(r.get("value_json"))
    if fk in ("coherence.option", "option"):
      # a corrected option id: the value is the id the client's words point to
      if tk in ("", fk) and isinstance(val, str) and val.strip() and val != original.get(fk):
        final[fk] = val.strip()
        rewrites.append({"from_key": fk, "to_key": fk, "client_words": r.get("client_words"), "receipt": r.get("receipt"),
                         "why": r.get("why"), "value": val.strip()})
      continue
    if fk not in original:
      continue   # a rewrite must start from a key the router proposed
    from client_intake_and_finmo.intake_guard.provenance import never_rewrite as _never_rw
    if _never_rw(fk) or _never_rw(tk):
      continue   # the estimator's bookkeeping has its own provenance; never a rewrite target
    if not _value_in_words(val, str(r.get("client_words") or "")):
      # the one limit: a figure the client did not state is not the guard's to write
      logger.error("INTAKE_GUARD_A_REWRITE_REFUSED value %r not in client words %r", val, r.get("client_words"))
      continue
    same_key = tk in ("", fk)
    current = fin_store.get(fk.split(".")[-1]) if fk.startswith("financials.") else None
    try:
      restores_store = same_key and current is not None and abs(float(current) - float(val)) <= max(0.005, abs(float(val)) * 0.001)
    except (TypeError, ValueError):
      restores_store = False
    final.pop(fk, None)
    if not restores_store and (same_key or tk):
      final[fk if same_key else tk] = val
    rewrites.append({"from_key": fk, "to_key": fk if same_key else tk, "client_words": r.get("client_words"),
                     "receipt": r.get("receipt"), "why": r.get("why"), "value": val})
  asks: List[Dict[str, Any]] = []
  for a in parsed.get("asks") or []:
    if isinstance(a, dict) and a.get("key") and a.get("question") and str(a["key"]) in original:
      asks.append({k: a.get(k) for k in ("key", "client_words", "question", "why")})
      final.pop(str(a["key"]), None)
  # a corrected option id offered through `allowed` without a rewrite entry counts as a rewrite too
  for k, v in allowed_ids.items():
    if k in original and isinstance(v, str) and v.strip() and v.strip() != original[k] and not any(x["from_key"] == k for x in rewrites):
      final[k] = v.strip()
      rewrites.append({"from_key": k, "to_key": k, "client_words": user_text, "receipt": "", "why": "option id corrected", "value": v.strip()})
  allowed = final
  return Verdict(patch=allowed, rewrites=rewrites, asks=asks, dropped=dropped, hold_cleared=bool(parsed.get("hold_cleared")),
                 ran=True, elapsed_ms=elapsed)
