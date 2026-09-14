"""DOOR B - the reply, before it goes out. ALWAYS, not on a phrase.

Nick 2026-09-12 (item 5): "Door B is trigger-based and that's the keyword
problem again. A claim regex and one literal phrase. The parked template
lied and matched neither. Door B compares the reply to the store, always,
on every turn - not when a phrase fires."

So: EVERY dollar figure in the reply must be explained - by a store leaf in
any common basis, by the walk's lever-writes record (from or to), by an
option's priced closure, by the gap arithmetic (any two gap-side figures'
difference: "closed by $1,104"), or by the client's own words this turn.
An unexplained figure is a disagreement, whatever verb sits next to it.
And on every WALK turn (the lever-writes record is non-empty) the model
compares the whole reply to that record regardless of wording - a reply
that says nothing moved, or presents a moved figure as the client's
original, is rewritten from the record. One row per turn is recorded.
The guard's own door-A receipts and questions are appended here, so the
reply that persists is the reply that is sent.

Fail OPEN on a timeout, logged loudly.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.intake_watcher.checks import (  # the deterministic reads, kept
  _close, _equivalents, figures_in, numeric_leaves,
)

logger = logging.getLogger(__name__)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_RETRYABLE = (408, 409, 425, 429, 500, 502, 503, 504)
DEADLINE_SECONDS = float(os.getenv("INTAKE_GUARD_DEADLINE_SECONDS") or 28.0)

# one deterministic signal kept (it is cheap and it is exactly what CW-062's
# template said); the model's comparison on every walk turn is the gate
_NOTHING_MOVED_RE = re.compile(r"(?i)nothing (?:you (?:told me|set) )?(?:has been |was )?moved")
_DOLLAR_RE = re.compile(r"\$\s?(\d[\d,]*\.?\d*)\s*(k|m|thousand|million)?\b", re.I)
#: EVERY NUMBER IN THE REPLY IS IN SCOPE (Nick 2026-09-13). The dollar sign
#: and the >= 100 threshold decided that 4 hulls, 33 people and 6 boats a year
#: were not figures - the keyword problem wearing a number's clothes. Door B's
#: job is whether the reply agrees with the STORE, so what gets compared cannot
#: be decided by how a number is written. Noise is answered by comparing
#: against what was actually written, not by filtering the input.
#: A MULTIPLIER IS A WHOLE WORD (2026-09-13, CW-069 replay turn 13). Without the
#: boundary "about 340 most weeks" read as 340 MILLION - the m of "most" - so her
#: own figure was unexplained and door B's rewrite deleted it. "12 months",
#: "5 miles", "40 more", "3 kits" were all being scaled the same way.
_ANY_NUMBER_RE = re.compile(r"(?<![\w.])\$?\s?(\d[\d,]*\.?\d*)\s*(k\b|m\b|thousand\b|million\b|%|percent\b)?", re.I)


def _model() -> str:
  return (os.getenv("INTAKE_GUARD_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def enabled() -> bool:
  return (os.getenv("INTAKE_GUARD_ENABLED") or "1").strip().lower() not in ("0", "false", "no", "off")


@dataclass
class ReplyVerdict:
  text: str
  disagreements: List[Dict[str, Any]] = field(default_factory=list)
  rewritten: bool = False
  ran_model: bool = False
  timed_out: bool = False
  error: str = ""
  elapsed_ms: int = 0
  appended: List[str] = field(default_factory=list)
  figures_found: int = 0
  compared_walk: bool = False
  correction: str = ""   # the client's correction in their latest message, when there was one
  raw_field_names: List[str] = field(default_factory=list)


def _store_leaves(store: Dict[str, Any]) -> Dict[str, float]:
  return numeric_leaves({k: v for k, v in (store or {}).items() if k in ("financials", "ops", "people")})


def _all_numeric(obj: Any, prefix: str = "") -> Dict[str, float]:
  """numeric_leaves skips private keys; the walk's record lives under
  financials._coherence and every figure there is one the reply may say."""
  out: Dict[str, float] = {}
  if isinstance(obj, dict):
    for k, v in obj.items():
      out.update(_all_numeric(v, f"{prefix}.{k}" if prefix else str(k)))
  elif isinstance(obj, list):
    for i, v in enumerate(obj):
      out.update(_all_numeric(v, f"{prefix}[{i}]"))
  elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
    if prefix:
      out[prefix] = float(obj)
  return out


_PCT_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")


from client_intake_and_finmo.reader_log import reads_client_words  # noqa: E402 - one-reader step 1b


@reads_client_words("door_b_said_numbers")
def said_numbers(text: str) -> List[float]:
  """Every figure the client's words carry, read by BOTH parsers. Door A's
  reads spelled numbers ("about three hundred and forty most weeks" - CW-069,
  where digits-only reading made her own 340 look invented); door C's reads
  "4.6 million" and "12 thousand". Either one alone loses a real figure."""
  out: List[float] = []
  try:
    from client_intake_and_finmo.intake_guard.door_a import numbers_in_words as _spelled
    out.extend(_spelled(str(text or "")))
  except Exception:
    pass
  try:
    from client_intake_and_finmo.intake_guard.door_c import numbers_in_words as _scaled
    out.extend(_scaled(str(text or "")))
  except Exception:
    pass
  return out


@reads_client_words("door_b_explained_figures")
def explained_figures(store: Dict[str, Any], lever_writes: Optional[Dict[str, Any]] = None, user_text: str = "",
                      reply_text: str = "", recent_user_texts: Optional[List[str]] = None) -> List[float]:
  """Every figure the reply is entitled to say: the store in any common
  basis, the walk's record, the option prices, the gap arithmetic, the
  client's words (this turn and the last few), and the app's own arithmetic
  on stored figures - a percentage the reply names applied to a stored
  figure, and the sum of two stored financial figures."""
  # A DERIVED FIGURE IS NOT ITS OWN EXPLANATION (2026-09-13, Cowork standing:
  # nothing derived is read back). annual_turns_per_year and utilization_rate
  # on a concurrent row are COMPUTED from the client's ceiling and actual
  # (34 / 6, 26 / 34). Counted as explanations, a reply reading "turning over
  # 5.67 times a year" back was explained by the very value it leaked. A figure
  # the client actually said is still explained - by her words, below.
  # Trade-off, named: a turns figure she stated more than four messages ago is
  # no longer explained by the store. Narrow - turns are almost always derived.
  # A derived percent or decimal is caught by derived_read_backs, below, by
  # what it IS (a ratio of two of her figures) rather than by being absent here.
  # The client's words are read with door A's parser, spelled numbers included:
  # CW-069 turn 11, "about three hundred and forty most weeks" read as nothing,
  # her own 340 looked invented, and the rewrite deleted it.
  # A spelled percentage or proportion in the REPLY is checked there too.
  # Known gap, NOT closed: a whole number the reply spells out ("twenty-four
  # thousand a year") - the consultant is told to say "the first twelve months",
  # and reading every spelled number as a claim would rewrite that each turn.
  vals: List[float] = [
    v for k, v in _store_leaves(store).items()
    if ([t for t in re.split(r"[.\[\]/]", str(k)) if t] or [""])[-1]
    not in ("annual_turns_per_year", "utilization_rate")
  ]
  fin_top = [v for k, v in _store_leaves(store).items() if k.startswith("financials.") and k.count(".") == 1 and v > 0]
  fin_top = sorted(set(round(x, 2) for x in fin_top))[:40]
  # TWO DIFFERENT FIGURES, NEVER ONE FIGURE TWICE (Nick ruled 2026-09-14). The
  # inner loop started at i, so every stored financial figure was also added to
  # itself and DOUBLE any stored figure read as explained - a reply saying
  # revenue is 3,359,200 against a stored 1,679,600 passed. It needed no client
  # sentence at all, only the store.
  for i in range(len(fin_top)):
    for j in range(i + 1, len(fin_top)):
      vals.append(fin_top[i] + fin_top[j])
  for m in _PCT_RE.finditer(str(reply_text or "")):
    try:
      pct = float(m.group(1)) / 100.0
    except ValueError:
      continue
    for base in fin_top:
      vals.append(base * pct)
  try:
    numbers_in_words = said_numbers
    for t in (recent_user_texts or [])[-4:]:
      vals.extend(numbers_in_words(t))
  except Exception:
    pass
  coh = ((store or {}).get("financials") or {}).get("_coherence") if isinstance((store or {}).get("financials"), dict) else None
  gap_side: List[float] = []
  if isinstance(coh, dict):
    for path, v in _all_numeric(coh, "_coherence").items():
      vals.append(v)
      leaf = path.split(".")[-1]
      if any(t in leaf for t in ("gap", "closes", "ebitda", "revenue", "payroll", "rent", "gna", "marketing", "cogs", "promised", "before", "after")):
        gap_side.append(v)
  for w in (lever_writes or {}).values():
    if isinstance(w, dict):
      for k in ("from", "to"):
        try:
          if w.get(k) is not None:
            vals.append(float(w[k]))
        except (TypeError, ValueError):
          pass
  try:
    numbers_in_words = said_numbers
    vals.extend(numbers_in_words(user_text))
  except Exception:
    pass
  # the gap arithmetic: "closed by $X" is the difference of two gap-side figures
  gs = sorted(set(round(x, 2) for x in gap_side))[:60]
  for i in range(len(gs)):
    for j in range(i + 1, len(gs)):
      vals.append(abs(gs[j] - gs[i]))
  return vals


def _dollar_figures(text: str) -> List[Dict[str, Any]]:
  """Every number the reply states, money or not.

  Was: dollar-prefixed AND >= 100. On Alderman & Fitch a88dae18 that meant
  every audit row read "figures:0/0 unexplained" while the reply carried four
  hulls a week, 33 people and six boats a year - door B could not have caught
  the capacity misstatement that ended the run, by construction.

  The reply's own numbering ("Option 1", a list marker) is structure, not a
  claim about the business, and a bare four-digit year is a date. Everything
  else is compared against what was actually written."""
  body = str(text or "")
  out: List[Dict[str, Any]] = []
  seen: set = set()
  for m in _ANY_NUMBER_RE.finditer(body):
    raw = m.group(1).rstrip(",.")   # the char class swallows a trailing comma
    try:
      v = float(raw.replace(",", ""))
    except ValueError:
      continue
    mult = (m.group(2) or "").lower()
    if mult in ("k", "thousand"):
      v *= 1000.0
    elif mult in ("m", "million"):
      v *= 1_000_000.0
    elif mult in ("%", "percent"):
      # A PERCENTAGE IS AN OPERATOR, NOT A CLAIM. explained_figures already
      # applies every percentage in the reply to the stored figures, which is
      # how "4%, which works out to $19,600 a year" is explained against a
      # $490,000 revenue. Checking the 4% as a figure in its own right
      # double-counts it and flags market context ("businesses like yours run
      # 3%-6%") as a disagreement. The figure it PRODUCES is what gets checked.
      continue
    before = body[max(0, m.start() - 14):m.start()]
    if re.search(r"(?:option|step|point|item|phase|#)\s*$", before, re.I):
      continue                      # the reply numbering itself
    if 1900 <= v <= 2100 and "." not in raw and "," not in raw and not mult:
      continue                      # a year
    key = round(v, 2)
    if key in seen:
      continue
    seen.add(key)
    s0 = max(0, m.start() - 90)
    out.append({"value": v,
                "money": body[max(0, m.start() - 2):m.start() + 1].find("$") >= 0,
                "sentence": body[s0:m.end() + 40].replace(chr(10), " ")})
  return out


_PCT_FIG_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b|per cent\b)", re.I)
_DECIMAL_FIG_RE = re.compile(r"(?<![\w.,$])(\d+\.\d+)(?![\d.]|\s*%|\s*per ?cent)", re.I)
_PCT_WORDS_RE = re.compile(r"((?:[a-z]+[\s-]+){1,5})(?:percent|per cent)\b", re.I)
_DERIVED_LEAVES = ("annual_turns_per_year", "utilization_rate")
_PROPORTION_WORDS = (
  ("three quarters", 0.75), ("a quarter", 0.25), ("one quarter", 0.25),
  ("two thirds", 2 / 3), ("a third", 1 / 3), ("one third", 1 / 3),
  ("four fifths", 0.8), ("three fifths", 0.6), ("two fifths", 0.4), ("a fifth", 0.2),
  ("nine tenths", 0.9),
)


def _client_texts(user_text: str, recent_user_texts: Optional[List[str]]) -> List[str]:
  return [str(t or "") for t in list(recent_user_texts or [])[-4:]] + [str(user_text or "")]


@reads_client_words("door_b_derived_read_backs")
def derived_read_backs(text: str, store: Dict[str, Any], user_text: str = "",
                       recent_user_texts: Optional[List[str]] = None) -> List[Dict[str, Any]]:
  """NOTHING DERIVED IS READ BACK (Cowork, standing) - caught by what it IS.

  CW-068 read her six and her 34 back as "5.67 times a year"; CW-069 read her
  340 and her 480 back as "about 70%" and asked her to plan on it. Same move,
  different trade: arithmetic on two figures the client gave, returned to her
  as a third she did not. Checking against the explanation set could not see
  either - a percentage was treated as an operator, and 5.67 sits inside the
  rounding tolerance of her six.

  So: a percentage, or a number stated with decimals, that is the ratio of two
  figures the client said - at the precision the reply states it (a whole
  percent within one point, "about 70%" of 70.83) - and that is not itself a
  figure or percentage she said, nor a stored rate, is a derived read-back.
  Whole numbers are left to the explanation check: small integers are ratios
  of something far too often to call. Multiplier words (hundred, thousand)
  are never a denominator - a share of "a hundred" is the figure itself."""
  _said = said_numbers
  body = str(text or "")
  texts = _client_texts(user_text, recent_user_texts)
  said: List[float] = []
  for t in texts:
    said.extend(_said(t))
  base = sorted({float(x) for x in said if x >= 1 and x not in (100.0, 1000.0, 1_000_000.0)})[:24]
  if len(base) < 2:
    return []
  stored = [
    v for k, v in _store_leaves(store).items()
    if ([t for t in re.split(r"[.\[\]/]", str(k)) if t] or [""])[-1] not in _DERIVED_LEAVES
  ]
  own_pcts: List[float] = [v * 100.0 for v in stored if 0 < v <= 1]
  for t in texts:
    own_pcts.extend(float(m.group(1)) for m in _PCT_FIG_RE.finditer(t))
    for m in _PCT_WORDS_RE.finditer(t):
      own_pcts.extend(_said(m.group(1)))
  out: List[Dict[str, Any]] = []
  seen: set = set()

  def _sentence(m: "re.Match[str]") -> str:
    return body[max(0, m.start() - 90):m.end() + 40].replace(chr(10), " ")[:160]

  for m in _PCT_FIG_RE.finditer(body):
    raw = m.group(1)
    p = float(raw)
    dp = len(raw.split(".")[1]) if "." in raw else 0
    half = 0.5 * 10 ** -dp
    if not 0 < p <= 100 or any(abs(p - q) <= half for q in own_pcts):
      continue
    tol = 1.0 if dp == 0 else half
    hit = next(((a, b) for a in base for b in base if a < b and abs(100.0 * a / b - p) <= tol), None)
    if hit and ("percent", p) not in seen:
      seen.add(("percent", p))
      out.append({"kind": "derived_figure_read_back", "value": p, "basis": "percent",
                  "computed_from": [hit[0], hit[1]], "sentence": _sentence(m)})
  # THE SAME FIGURE IN WORDS (Cowork 1023, escalated before the claim). The
  # reply's figures were read in digits only - the CW-069 blindness with the
  # arrow reversed - and asking the consultant for plainer prose pushes it
  # toward exactly "about seventy percent" and "three-quarters full". A spelled
  # percentage is checked like a digit one; a proportion word is checked when it
  # is used AS a proportion ("of", "full", "capacity"), never "a third line".
  _client_l = " ".join(texts).lower()
  for m in _PCT_WORDS_RE.finditer(body):
    if re.search(r"\d", m.group(1)):
      continue                      # digits are the loop above
    spoken = [v for v in _said(m.group(1)) if 0 < v <= 100]
    if not spoken:
      continue
    p = max(spoken)
    if any(abs(p - q) <= 0.5 for q in own_pcts):
      continue
    hit = next(((a, b) for a in base for b in base if a < b and abs(100.0 * a / b - p) <= 1.0), None)
    if hit and ("percent", p) not in seen:
      seen.add(("percent", p))
      out.append({"kind": "derived_figure_read_back", "value": p, "basis": "percent_in_words",
                  "computed_from": [hit[0], hit[1]], "sentence": _sentence(m)})
  for phrase, frac in _PROPORTION_WORDS:
    pat = re.compile(r"\b" + phrase.replace(" ", r"[\s-]+") + r"\s+(?:of\b|full\b|capacity\b|booked\b|busy\b)", re.I)
    m = pat.search(body)
    if not m or re.search(r"\b" + phrase.replace(" ", r"[\s-]+") + r"\b", _client_l):
      continue
    hit = next(((a, b) for a in base for b in base if a < b and abs(a / b - frac) <= 0.02), None)
    if hit and ("words", frac) not in seen:
      seen.add(("words", frac))
      out.append({"kind": "derived_figure_read_back", "value": frac, "basis": "proportion_in_words",
                  "computed_from": [hit[0], hit[1]], "sentence": _sentence(m)})
  for m in _DECIMAL_FIG_RE.finditer(body):
    raw = m.group(1)
    v = float(raw)
    half = 0.5 * 10 ** -len(raw.split(".")[1])
    if any(abs(v - s) <= half for s in said) or any(abs(v - s) <= half for s in stored):
      continue
    hit = next(((a, b) for a in base for b in base if a != b and abs(a / b - v) <= half), None)
    if hit and ("ratio", v) not in seen:
      seen.add(("ratio", v))
      out.append({"kind": "derived_figure_read_back", "value": v, "basis": "ratio",
                  "computed_from": [hit[0], hit[1]], "sentence": _sentence(m)})
  return out


def find_disagreements(text: str, store: Dict[str, Any], lever_writes: Optional[Dict[str, Any]] = None,
                       user_text: str = "", recent_user_texts: Optional[List[str]] = None) -> List[Dict[str, Any]]:
  """Deterministic, on EVERY figure: a figure the app derived from the
  client's own and read back; a figure the reply states that nothing entitles
  it to say; and the literal 'nothing moved' against a non-empty lever-writes
  record (one cheap signal kept, not the gate)."""
  out: List[Dict[str, Any]] = derived_read_backs(text, store, user_text, recent_user_texts)
  _derived_ratios = [d["value"] for d in out if d.get("basis") == "ratio"]
  vals = explained_figures(store, lever_writes, user_text, reply_text=text, recent_user_texts=recent_user_texts)
  for fig in _dollar_figures(text):
    v = fig["value"]
    if any(abs(v - dv) < 1e-9 for dv in _derived_ratios):
      continue                      # already named for what it is
    if any(_close(s, e) for s in vals for e in _equivalents(v)):
      continue
    out.append({"kind": "claimed_figure_not_in_store", "value": v, "sentence": fig["sentence"][:160]})
  if _NOTHING_MOVED_RE.search(text or "") and any(
      isinstance(w, dict) and w.get("from") is not None and w.get("to") is not None
      and abs(float(w["from"]) - float(w["to"])) > 0.5 for w in (lever_writes or {}).values()):
    out.append({"kind": "nothing_moved_but_writes", "value": None,
                "sentence": "nothing moved by the levers", "writes": list((lever_writes or {}).keys())})
  return out


SCHEMA = {
  "type": "object", "additionalProperties": False,
  "properties": {"reply": {"type": "string"}, "changed": {"type": "boolean"}, "why": {"type": "string"}},
  "required": ["reply", "changed", "why"],
}

SYSTEM = (
  "You check the consultant's reply to a small-business owner against the store of what the owner has told us "
  "and against `lever_writes` - the record of every figure the planning walk moved, from what the owner first "
  "said to where it is now - before the reply is sent. Contradictions to fix: a figure the store does not hold "
  "(any listed in `disagreements`); a claim that nothing has moved or that every figure is as the owner set it "
  "when lever_writes shows moves; a moved figure presented as the owner's original; a moved figure stated at its "
  "old value as if current. Rewrite ONLY the contradicting sentences so they state what the store and "
  "lever_writes hold, in the owner's own language, and keep every other sentence exactly as it is. Never "
  "introduce a figure that is not in the store, lever_writes or the owner's words. If nothing contradicts, or "
  "the contradiction cannot be fixed from the store, keep the reply and set changed=false.\n"
  "A disagreement of kind derived_figure_read_back is a number the consultant COMPUTED from the owner's own "
  "figures - a share, percentage, ratio or turns figure; computed_from names the two. Nothing derived is ever "
  "read back or offered for agreement: remove that figure and the wording that proposes it, never replace it "
  "with another computed figure, and if the sentence asked the owner to agree to it, ask instead for the figure "
  "in the owner's own terms (for example how many they actually do in a normal week, or how many they finish in "
  "a year). NEVER remove, round or change a figure the owner stated - `owner_words` holds their own recent messages; "
  "a figure found there is theirs, whether they wrote it in digits or spelled "
  "it out in words ('about three hundred and forty' is the owner's 340).\n"
  "THE THIRD QUESTION - DID THE REPLY ANSWER WHAT THE OWNER JUST CORRECTED? When `correction` is non-empty the "
  "owner has just corrected the consultant in those words ('that is not quite what I said - contractually they can "
  "move, but I do not want them moved in year one; please record that as a constraint, not as permission'). The "
  "reply must acknowledge the correction before anything else and read back what the owner said as a fact about "
  "their business, in their words ('Understood - not fixed by contract, and you do not want prices moved in year "
  "one; I'll leave them alone in year one.'). If the reply does not, prepend that one sentence, built only from "
  "the owner's words, keep the rest exactly as it is, and set changed=true. Never restate an owner's limit as "
  "permission ('prices can move', 'we can look at rent')."
)

_CORRECTION_RE = re.compile(
  r"not (quite )?what i (said|meant|told you)|that'?s not (what i said|right|it)|please record (that|this|it) as|"
  r"record that as a|i did not say|i didn'?t say|i never said|as a constraint, not|correction:|to be clear[,:]",
  re.I)


def _post_rewrite(text: str, disagreements: List[Dict[str, Any]], store: Dict[str, Any],
                  lever_writes: Optional[Dict[str, Any]], post, correction: str = "",
                  owner_words: Optional[List[str]] = None) -> ReplyVerdict:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    logger.error("INTAKE_GUARD_B_NO_KEY - reply sent unguarded")
    return ReplyVerdict(text=text, disagreements=disagreements, error="no_api_key")
  fin = {k: v for k, v in ((store.get("financials") or {}).items()) if not str(k).startswith("_")}
  body = {"reply": text, "disagreements": disagreements, "store_financials": fin,
          "lever_writes": lever_writes or {}, "ops_lines": (store.get("ops") or {}).get("lob_models"),
          "correction": correction or "",
          # THE OWNER'S OWN WORDS (2026-09-13, CW-069 turns 11 and 13): told never
          # to remove a figure the owner stated, the model could not see what the
          # owner stated - twice it removed her 340 as "not in the store"
          "owner_words": [w for w in (owner_words or []) if str(w or "").strip()]}
  payload = {"model": _model(),
             "input": [{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": json.dumps(body, ensure_ascii=False, default=str)}],
             "text": {"format": {"type": "json_schema", "name": "intake_guard_door_b", "schema": SCHEMA, "strict": True}},
             "store": False}
  t0 = time.monotonic()
  try:
    resp = post(url=OPENAI_RESPONSES_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload=payload, timeout_seconds=DEADLINE_SECONDS, retryable_status=_RETRYABLE, max_attempts=1)
    if resp.status_code >= 400:
      logger.error("INTAKE_GUARD_B_HTTP_%s - reply sent unguarded", resp.status_code)
      return ReplyVerdict(text=text, disagreements=disagreements, ran_model=True, error=f"http_{resp.status_code}",
                          elapsed_ms=int((time.monotonic() - t0) * 1000))
    data = resp.json()
    parsed = None
    for item in data.get("output") or []:
      for part in item.get("content", []) or []:
        if part.get("type") == "output_text" and part.get("text"):
          parsed = json.loads(part["text"])
  except Exception as exc:  # noqa: BLE001 - FAIL OPEN, LOUDLY
    logger.error("INTAKE_GUARD_B_TIMEOUT_OR_ERROR after %.1fs - reply sent unguarded: %s: %s",
                 time.monotonic() - t0, type(exc).__name__, exc)
    return ReplyVerdict(text=text, disagreements=disagreements, ran_model=True, timed_out=True,
                        error=f"{type(exc).__name__}: {exc}"[:300], elapsed_ms=int((time.monotonic() - t0) * 1000))
  elapsed = int((time.monotonic() - t0) * 1000)
  if not isinstance(parsed, dict) or not parsed.get("changed") or not str(parsed.get("reply") or "").strip():
    return ReplyVerdict(text=text, disagreements=disagreements, ran_model=True, elapsed_ms=elapsed)
  new_text = str(parsed["reply"]).strip()
  # the rewrite may not introduce a figure nothing entitles it to say (the
  # store, the lever-writes record, the gap arithmetic, the app's arithmetic)
  leaves = explained_figures(store, lever_writes, reply_text=text)
  for v in figures_in(new_text, at_least=100.0):
    if v in figures_in(text, at_least=100.0):
      continue
    if not any(_close(s, e) for s in leaves for e in _equivalents(v)):
      logger.error("INTAKE_GUARD_B_REWRITE_REFUSED introduced %s not in store - original reply sent", v)
      return ReplyVerdict(text=text, disagreements=disagreements, ran_model=True, elapsed_ms=elapsed,
                          error="rewrite_introduced_figure")
  return ReplyVerdict(text=new_text, disagreements=disagreements, rewritten=True, ran_model=True, elapsed_ms=elapsed)


_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_HEAD_RE = re.compile(r"(?m)^#{1,4}\s+")


def strip_markdown_emphasis(text: str) -> str:
  t = _MD_BOLD_RE.sub(lambda m: m.group(1), str(text or ""))
  return _MD_HEAD_RE.sub("", t)


def raw_field_names_spoken(text: str) -> List[str]:
  """Field keys the reply says out loud, de-underscored.

  THE ONLY PLACE THIS CLASS CAN BE CAUGHT IS AT RUNTIME (2026-09-13). Twice in
  one day a raw key reached a client - "units per period capacity" from the
  unapplied-fields note, and "your concurrent capacity units are now updated to
  12" the first time a per-line concurrent capacity was ever recorded. The
  second was not our template at all: the model read the key out of its own
  context. No test over our source can see that, because we did not write the
  sentence.

  So the reply itself is read, every turn, against the vocabulary of real field
  keys. This REPORTS rather than rewrites - rewriting a consultant's prose
  mid-turn is its own risk, and an audit row that names the key is enough to
  find the field that was added without words.
  """
  said = " ".join(str(text or "").split()).lower()
  if not said:
    return []
  try:
    from client_intake_and_finmo.intake_required_fields import (  # type: ignore
      FIELD_LABELS as _names,
    )
    vocabulary = list(_names.keys())
  except Exception:
    vocabulary = []
  vocabulary += [
    "units_per_week_capacity", "units_per_period_capacity",
    "concurrent_capacity_units", "annual_turns_per_year",
    "operating_periods_per_year", "utilization_rate", "unit_price",
    "unit_cadence", "cogs_percent_of_line_revenue", "lob_models",
  ]
  # KEPT BROAD, DELIBERATELY (2026-09-13, after watching it live).
  #
  # A narrowing to 'only fields we have no name for' was written and reverted
  # within the same run: it would have suppressed ['annual turns per year'],
  # which IS a raw key reaching a client and which DOES have a label. The
  # noise it was meant to remove was ['legal entity'] - ordinary business
  # English that happens to match a key.
  #
  # No rule I trust separates 'legal entity' from 'annual turns per year' by
  # inspecting the string, so this stays broad and stays LOG-ONLY. A false
  # positive costs a glance; a false negative cost two client-visible leaks in
  # one day. It is a triage signal for a human, not a gate.
  spoken: List[str] = []
  for key in set(vocabulary):
    leaf = str(key or '').split('.')[-1]
    if '_' not in leaf:
      continue                 # a single word is not recognisably a key
    phrase = leaf.replace('_', ' ').lower()
    if phrase in said and phrase not in spoken:
      spoken.append(phrase)
  return spoken


def review(*, text: str, store: Dict[str, Any], lever_writes: Optional[Dict[str, Any]] = None,
           receipts: Optional[List[str]] = None, questions: Optional[List[str]] = None, post=None,
           user_text: str = "", recent_user_texts: Optional[List[str]] = None) -> ReplyVerdict:
  """The door. Every figure is compared, every turn; the model compares the
  whole reply to the lever-writes record on every WALK turn (the record is
  non-empty) and on any unexplained figure. Door A's receipts and questions
  are appended so they reach the client."""
  base = str(text or "")
  verdict = ReplyVerdict(text=base)
  if enabled() and base.strip():
    dis = find_disagreements(base, store, lever_writes, user_text, recent_user_texts)
    verdict.disagreements = dis
    verdict.figures_found = len(_dollar_figures(base))
    # A RAW FIELD KEY IN THE REPLY (2026-09-13). Reported, not rewritten:
    # rewriting a consultant's prose mid-turn is its own risk, and an audit
    # row naming the key is what finds the field that was given a schema, a
    # router and a writer but no words. Twice in one day: "units per period
    # capacity" from our own note, and "your concurrent capacity units are
    # now updated to 12" from the model reading the key out of its own
    # context - which no test over our source could ever see.
    verdict.raw_field_names = raw_field_names_spoken(base)
    if verdict.raw_field_names:
      logger.warning(
        "DOOR_B_RAW_FIELD_NAME_IN_REPLY %s", verdict.raw_field_names)
    walk_turn = any(isinstance(w, dict) and w.get("to") is not None for w in (lever_writes or {}).values())
    # THE THIRD QUESTION (Nick 2026-09-13, Sorrel & Dunne 691a4763): "that is
    # not quite what I said" is the strongest signal a client can give, and
    # nothing looked for it - the next reply was about marketing. A correction
    # in the client's latest message always sends the reply to the model,
    # which must find the acknowledgement or add it in the client's words.
    correction = str(user_text or "").strip() if _CORRECTION_RE.search(str(user_text or "")) else ""
    verdict.correction = correction
    if dis or walk_turn or correction:
      if post is None:
        from client_intake_and_finmo.openai_http import post_openai_with_retries as post  # type: ignore
      verdict = _post_rewrite(base, dis, store, lever_writes, post, correction=correction,
                              owner_words=_client_texts(user_text, recent_user_texts))
      verdict.correction = correction
      verdict.figures_found = len(_dollar_figures(base))
      verdict.compared_walk = walk_turn
  # the panel renders text raw: markdown emphasis from the naturaliser would
  # reach the client as asterisks (guarded run 2, turn 52: "**$11,313**")
  verdict.text = strip_markdown_emphasis(verdict.text)
  extras: List[str] = []
  # A RECEIPT NAMES ONLY WHAT THE CLIENT SAID (Cowork, 2026-09-13, standing).
  #
  # Door A's receipts were appended here verbatim, and the raw-field-name read
  # above runs on the consultant's text BEFORE they are added - so on
  # Vasquez-Lindqvist ec2da9c7 the client was about to be told "...and not as
  # 2.6 annual turns per year": a number she never said and a slot name, inside
  # the receipt that corrected them. A readback rule that lives only in a
  # prompt is not enforced. So a receipt that speaks a field key, or a figure
  # absent from the client's own words, does not go out. The catch still
  # happened - the patch was rewritten - only the sentence is withheld.
  try:
    _niw = said_numbers
  except Exception:
    _niw = None
  _said: List[float] = []
  if _niw is not None:
    for _t in [user_text] + list(recent_user_texts or []):
      try:
        _said.extend(_niw(str(_t or "")))
      except Exception:
        pass

  def _client_said_it(value: float) -> bool:
    return any(abs(value - s) <= max(1e-6, 0.005 * abs(s)) for s in _said)

  for r in receipts or []:
    if not r or r in verdict.text:
      continue
    _keys = raw_field_names_spoken(r)
    _unsaid: List[float] = []
    if _niw is not None:
      try:
        _unsaid = [v for v in _niw(r) if not _client_said_it(v)]
      except Exception:
        _unsaid = []
    if _keys or _unsaid:
      logger.warning(
        "DOOR_B_RECEIPT_WITHHELD keys=%s unsaid_figures=%s - a readback names "
        "the figures the client said, or nothing", _keys, _unsaid)
      continue
    # A RECEIPT THAT ADDS NOTHING IS NOT SAID (2026-09-13, Vasquez-Lindqvist
    # ec2da9c7 replay turn 19). The store was right and every figure was hers,
    # and the client still read six, 26 and 34 three times - the third time
    # after the next question. When every figure in a receipt is already
    # stated in the reply, it tells her nothing she has not just read.
    if _niw is not None:
      try:
        _r_figs = _niw(r)
        _reply_figs = _niw(verdict.text)
      except Exception:
        _r_figs, _reply_figs = [], []
      if _r_figs and all(
          any(abs(v - w) <= max(1e-6, 0.005 * abs(w)) for w in _reply_figs)
          for v in _r_figs):
        logger.info(
          "DOOR_B_RECEIPT_REDUNDANT figures=%s - the reply already states every one",
          _r_figs)
        continue
    extras.append(r)
  receipt_extras = list(extras)
  question_extras: List[str] = []
  for q in questions or []:
    if q and q not in verdict.text:
      question_extras.append(q)
  if receipt_extras:
    # A RECEIPT COMES BEFORE THE QUESTION. It is the record of what was done;
    # the question is what the turn is waiting on. Appended at the end, it
    # left the message ending on a statement, after the question it should
    # have led into.
    _paras = verdict.text.rstrip().split("\n\n")
    _block = " ".join(receipt_extras)
    if len(_paras) > 1 and _paras[-1].rstrip().endswith("?"):
      verdict.text = "\n\n".join(_paras[:-1] + [_block, _paras[-1]]).strip()
    else:
      verdict.text = (verdict.text.rstrip() + "\n\n" + _block).strip()
  if question_extras:
    verdict.text = (verdict.text.rstrip() + "\n\n" + " ".join(question_extras)).strip()
  extras = receipt_extras + question_extras
  if extras:
    verdict.appended = extras
  return verdict
