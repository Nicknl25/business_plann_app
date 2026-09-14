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
from typing import Any, Dict, List, Optional, Tuple

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
    "already_captured": {
      "type": "array",
      "description": "for every numeric key: the items the client named that belong to a line the store already holds - empty when none",
      "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
          "key": {"type": "string"},
          "items": {"type": "string"},
          "captured_line": {"type": "string"},
          "question": {"type": "string"},
        },
        "required": ["key", "items", "captured_line", "question"],
      },
    },
  },
  "required": ["allowed", "rewrites", "asks", "hold_cleared", "already_captured"],
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
  "- A receipt names ONLY figures the client said, in their words, and says what was RECORDED. It never names "
  "the value that was avoided, never states a number the client did not say, and never names a field or slot. "
  "Right: 'You told me six at once is the most the building will hold, so I'm recording six frames in the shop "
  "at once.' Wrong: '...and not as 2.6 annual turns per year' - 2.6 is a number the client never said and "
  "'annual turns per year' is a field. Derived figures (turns, utilisation, anything you computed) are never "
  "read back. A receipt that breaks this rule is withheld before it reaches the client.\n"
  "3. ASK (in `asks`, and the key left out of `allowed`): the right home for the figure is GENUINELY ambiguous "
  "from their words. Give the question you would ask, plainly. Ask only when you cannot tell; a van lease "
  "payment sitting in rent is not ambiguous.\n"
  "4. ALREADY CAPTURED (in `asks`, and the key left out of `allowed`): the client's words name things that "
  "belong to a line the store ALREADY holds - materials, ingredients, packaging, containers or supplies inside "
  "direct costs; wages inside payroll; the premises inside rent; advertising inside marketing - so the figure "
  "would count them twice. A client who answers the other-bills question with 'green coffee, cans, kegs, cold "
  "storage, fuel, insurance' after direct costs were captured at 32% is not stating a new fact; they are mixing "
  "two lines. That is a question, not a write: ask which part of the figure belongs to the line in view, "
  "naming the items they mentioned and the line that already holds them ('You told me cleaning supplies are "
  "inside the 6% direct costs - is the $2,500 besides those, or does it include them?'). This move is yours "
  "even when the figure is exactly what they said.\n\n"
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
  "the patch), false otherwise.\n"
  "BEFORE YOU ALLOW ANY NUMERIC KEY, answer this for it in `already_captured`: do the things the client named "
  "with this figure belong to a line the store already holds? Look at their words for what the money is FOR "
  "(materials, ingredients, packaging, containers, supplies, stock -> direct costs when the store holds a "
  "cogs_percent_of_revenue or current_cogs; wages, salaries, a named person -> payroll; the space, the "
  "premises -> rent; advertising -> marketing). If any of it does, add one entry (the key, the items in their "
  "words, the line that already holds them, the question you would ask) and leave the key OUT of `allowed`. "
  "'$2,500 a month - cleaning supplies, van fuel, insurance, software and phones' against a stored 6% direct "
  "costs is an entry: items 'cleaning supplies', captured_line 'direct costs (6% of revenue)', question "
  "'You told me cleaning supplies are inside the 6% direct costs - is the $2,500 besides those, or does it "
  "include them?'. When nothing they named belongs elsewhere, the array is empty. Two things are NOT an entry: "
  "a figure the client THEMSELVES place inside another line ('$2,400 a month for the vans, and that's inside the "
  "$14,500 of other bills') - they have already told you where it lives, so rewrite or allow, never ask; and a "
  "figure given for a question that asks for THE REST ('the rest of the team', 'the other lines', 'besides "
  "payroll, marketing and rent') - the question itself excluded what the store holds. Nor is a BALANCE: stock "
  "on hand, cash, receivables, payables, equipment are what the business holds today, not the cost lines it "
  "spends - '$3,000 of cleaning supplies in stock' against a direct-cost share is inventory, not a double count."
)


# keys the ALREADY CAPTURED judgment never holds: questions that ask for the
# REST (the pool excludes the named people by construction) and balance-sheet
# stocks (inventory on hand is not the direct-cost flow; cash is not revenue)
_NEVER_ALREADY_CAPTURED = frozenset({
  "rest_of_team_payroll_year1", "inventory_balance", "cash_on_hand", "ar_balance", "ap_balance",
  "initial_assets", "initial_equity", "total_debt_outstanding", "capital_lease_balance",
})


def _leaf_of(key: str) -> str:
  return re.sub(r"\[\d+\]$", "", str(key or "").split(".")[-1])


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


_NUMBER_WORDS = {
  "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
  "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
  "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
  "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000, "million": 1_000_000,
  "half": 0.5, "dozen": 12,
}
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b", re.I)


def numbers_in_words(words: str) -> List[float]:
  """Every number the client's words carry: digits (with commas, decimals,
  a k/m suffix) and plain number words. 'thirty-six' reads as 30 and 6;
  'twenty-five' as 20 and 5 - the bases below cover what matters."""
  text = str(words or "")
  found: List[float] = []
  for m in _NUM_RE.finditer(text):
    raw = m.group(0).replace(",", "")
    try:
      found.append(float(raw))
    except ValueError:
      pass
  for m in re.finditer(r"(?<![\d.,])(\d+(?:\.\d+)?)\s*([kKmM])\b", text):
    try:
      found.append(float(m.group(1)) * (1000.0 if m.group(2).lower() == "k" else 1_000_000.0))
    except ValueError:
      pass
  for m in _NUMBER_WORD_RE.finditer(text):
    found.append(float(_NUMBER_WORDS[m.group(1).lower()]))
  # COMPOUND NUMBER WORDS (R23, CW-028 #4): 'one hundred and eighty-five' is
  # 185 - the fragments alone would call the router's 185 unsaid
  found.extend(_compound_number_words(text))
  return found


def _compound_number_words(text: str) -> List[float]:
  """Every run of number words ('thirty-six', 'one hundred and eighty-five',
  'two hundred fifty thousand') as one value."""
  out: List[float] = []
  tokens = re.findall(r"[A-Za-z]+|[-]", str(text or ""))
  run: List[str] = []
  def flush() -> None:
    if len(run) < 2:
      run.clear()
      return
    total = 0.0
    current = 0.0
    for w in run:
      v = _NUMBER_WORDS.get(w)
      if v is None:
        continue
      if v == 100:
        current = (current or 1.0) * 100.0
      elif v >= 1000:
        total += (current or 1.0) * v
        current = 0.0
      else:
        current += v
    total += current
    if total > 0:
      out.append(float(total))
    run.clear()
  for tok in tokens:
    lw = tok.lower()
    if lw in _NUMBER_WORDS and lw not in ("half",):
      run.append(lw)
    elif lw in ("and", "-") and run:
      continue
    else:
      flush()
  flush()
  return out


def _store_numbers(store: Optional[Dict[str, Any]]) -> List[float]:
  """Every number the store already holds (stated facts, lines, wages) -
  a value the client gave earlier may be restated or combined."""
  out: List[float] = []
  def walk(o: Any, depth: int = 0) -> None:
    if depth > 6:
      return
    if isinstance(o, dict):
      for k, v in o.items():
        if str(k).startswith("_"):
          continue
        walk(v, depth + 1)
    elif isinstance(o, list):
      for v in o[:200]:
        walk(v, depth + 1)
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
      try:
        f = float(o)
      except (TypeError, ValueError):
        return
      if f != 0.0 and abs(f) < 1e13:
        out.append(f)
  walk(store or {})
  return out


def _number_is_said(value: Any, words: str, store: Optional[Dict[str, Any]] = None) -> bool:
  """TAKE WHAT YOU ASKED FOR (Nick 2026-09-13): a number on a stated-fact
  field must be one the client said - in this message, in any common basis
  (per month, per year, per quarter, per week, thousands, millions, a
  percent) - or one the store already holds (a restatement), or arithmetic
  on a said number and a held one (slots x turns a year / 52 = capacity a
  week). An unsaid 1 matches none of these."""
  if value is True or value is False:
    return True
  try:
    v = float(value)
  except (TypeError, ValueError):
    return True
  tol = max(0.005, abs(v) * 0.005)
  said = numbers_in_words(words)
  held = _store_numbers(store)
  for f in held:
    if abs(f - v) <= tol:
      return True
  for f in said:
    for e in (f, f * 12, f / 12, f * 4, f / 4, f * 52, f / 52, f * 1000, f * 1_000_000, f / 100):
      if abs(e - v) <= tol:
        return True
    for g in said + held:
      if g == f:
        continue
      p = f * g
      for e in (p, p / 52, p / 12, p / 4, p / 100):
        if abs(e - v) <= tol:
          return True
  return False


def drop_unsaid_numbers(patch: Dict[str, Any], user_text: str, store: Optional[Dict[str, Any]] = None
                        ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  """THE SAME CLASS AS AN UNSAID ZERO, A DIFFERENT NUMBER (Nick 2026-09-13,
  Wren & Calloway 07a5b10f): the router wrote a unit price of 1 from 'About
  33 a year per slot'. When the client's words carry numbers, a number on a
  stated-fact leaf that is neither said nor held nor arithmetic on both is
  dropped here, deterministically, before and regardless of the model.
  Words with no number at all are left to the model (a cadence word can
  legitimately become a count)."""
  from client_intake_and_finmo.intake_guard.provenance import is_stated_fact
  words = str(user_text or "")
  if not numbers_in_words(words):
    return dict(patch or {}), []
  kept: Dict[str, Any] = {}
  dropped: List[Dict[str, Any]] = []
  for k, v in (patch or {}).items():
    key = str(k)
    if (is_stated_fact(key) and isinstance(v, (int, float)) and not isinstance(v, bool)
        and not _number_is_said(v, words, store)):
      dropped.append({"key": key, "value": v, "client_words": words, "action": "dropped_unsaid_number",
                      "why": "a number the client did not say is not a value - their words carry other figures, "
                             "the store holds others, and this is neither"})
      continue
    kept[key] = v
  return kept, dropped


def _value_in_words(value: Any, words: str) -> bool:
  """A NUMBER on a stated-fact leaf must appear in the client's words, in a
  common basis: as stated, per month, per year, per quarter, per week, in
  thousands or millions, or as a percent. Wren & Calloway 07a5b10f
  (2026-09-12): the old tolerance of 0.5 let a placeholder 1.0 match a
  stated 6 divided by 4 - now half a percent, never looser than a cent."""
  if value is True or value is False:
    return True
  try:
    v = float(value)
  except (TypeError, ValueError):
    return True   # not a number: a label or a choice
  for f in numbers_in_words(words):
    for e in (f, f * 12, f / 12, f * 4, f / 4, f * 52, f / 52, f * 1000, f * 1_000_000, f / 100):
      if abs(e - v) <= max(0.005, abs(v) * 0.005):
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
  original, dropped_numbers = drop_unsaid_numbers(original, user_text, store)
  dropped = list(dropped) + list(dropped_numbers)
  for d in dropped:
    logger.error("INTAKE_GUARD_A_%s %s=%r words=%r", str(d.get("action") or "dropped_unsaid_zero").upper(),
                 d["key"], d["value"], str(user_text or "")[:120])
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
      # THE SAME CLASS AS AN UNSAID ZERO (Nick 2026-09-13, Wren & Calloway
      # 07a5b10f): the model called the router's unit price of 1 "a
      # placeholder the client never said" and rewrote it onto the line; the
      # rewrite's 1.0 slipped the old loose matcher. Now, when the model has
      # judged the router's number wrong AND the router's number is not in
      # the client's own message either, neither number is written: the key
      # is dropped and the record says why. A router number the client did
      # say stays (the model was wrong to touch it).
      if fk in final and not _value_in_words(original.get(fk), str(user_text or "")):
        final.pop(fk, None)
        dropped.append({"key": fk, "value": original.get(fk), "client_words": str(user_text or ""),
                        "action": "dropped_unsaid_number",
                        "why": "the model judged the router's number a placeholder the client never said, and its "
                               "replacement was not in the client's words either - neither is written"})
        logger.error("INTAKE_GUARD_A_DROPPED_UNSAID_NUMBER %s=%r words=%r", fk, original.get(fk), str(user_text or "")[:120])
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
  # ALREADY CAPTURED (Nick 2026-09-13): the mandatory per-key judgment - an
  # entry is a question, not a write, whatever the model put in `allowed`
  for e in parsed.get("already_captured") or []:
    if not isinstance(e, dict) or not e.get("key") or not str(e.get("question") or "").strip():
      continue
    k = str(e["key"])
    if k not in original or any(a.get("key") == k for a in asks):
      continue
    # IN CODE, not the prompt: a question that asks for THE REST cannot be a
    # double count (the rest-of-team pool excludes the named people by
    # construction), and a balance-sheet stock is not a cost line
    if _leaf_of(k) in _NEVER_ALREADY_CAPTURED:
      logger.info("INTAKE_GUARD_A_ALREADY_CAPTURED_IGNORED key=%s (asks for the rest / a balance)", k)
      continue
    # and a balance the store holds (inventory on hand, cash) never makes a cost
    # line "already captured" - the walk persona's 6% direct costs were held
    # against its $3,000 of supplies in stock
    if re.search(r"inventor|in stock|stock on hand|on hand|cash|balance|receivable|payable", str(e.get("captured_line") or ""), re.I):
      logger.info("INTAKE_GUARD_A_ALREADY_CAPTURED_IGNORED key=%s (captured line is a balance: %s)", k, e.get("captured_line"))
      continue
    asks.append({"key": k, "client_words": str(e.get("items") or ""), "question": str(e["question"]).strip(),
                 "why": f"names {e.get('items')} - already inside {e.get('captured_line')}"})
    final.pop(k, None)
  # a corrected option id offered through `allowed` without a rewrite entry counts as a rewrite too
  for k, v in allowed_ids.items():
    if k in original and isinstance(v, str) and v.strip() and v.strip() != original[k] and not any(x["from_key"] == k for x in rewrites):
      final[k] = v.strip()
      rewrites.append({"from_key": k, "to_key": k, "client_words": user_text, "receipt": "", "why": "option id corrected", "value": v.strip()})
  allowed = final
  return Verdict(patch=allowed, rewrites=rewrites, asks=asks, dropped=dropped, hold_cleared=bool(parsed.get("hold_cleared")),
                 ran=True, elapsed_ms=elapsed)
