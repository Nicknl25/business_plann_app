"""THE INTERPRETATION CONTRACT, v1 - IN SHADOW (one-reader build, step 1).

Nick ruled 2026-09-14: a client's sentence is read ONCE, and everything
downstream works from that reading. Before anything is cut over, the v1
contract runs beside the app on every client turn, recorded and never used,
so what it costs and what it reads can be measured instead of assumed (R5).

What it records per turn, per claim: the quantity with what it is per, its
kind, its line, precision, polarity (a no is a fact), firmness with direction
and reason, provenance, whether it answered the question or came alongside,
what it supersedes and what it points at - and, for every claim, the SURFACE:
the smallest span of her message containing the value, its unit and its
qualifier, copied verbatim. Cowork, 1052: the quote proves the words are hers;
the readback proves the reading is hers. A span the reader picks freely is one
it can pick around its own mistake, so the span is chosen by rule.

Answers carry the app's question and an outcome, DECLINE first-class (A-171 read
a no as a yes; A-170 dropped a refusal three times). Derived figures are never
claims - the app computes them later from claims, by a named rule.

Shadow rules, all load-bearing:
  - it reads the sentence at the top of the turn, before any save or branch, on
    a snapshot of the turn's context taken on the request thread;
  - it runs in a background thread, so the client's reply is not slowed and no
    write can change;
  - it is OFF unless INTAKE_SHADOW_INTERPRETATION is on (the start script turns
    it on for the bounded window);
  - its failures are recorded and never raised;
  - the quote check (R2, string equality) is RECORDED here, not enforced.

v1.2 (Nick ruled 2026-09-14, Cowork 1078):
  - EVERY STRING FIELD IS CLASSIFIED (STRING_FIELDS): a span quoted from her
    message, a span quoted from the app's last message, a machine field drawn
    from a closed set, or an enum. Everything the contract writes is verbatim, an
    enum, a number, or a reference into a closed set. A machine field never
    reaches a client and never carries a figure.
  - R2 COMPARES AGAINST A STATED NORMAL FORM (normal_form). A quote is exact,
    normalised (true only after the normal form - it passes, logged loudly as
    SHADOW_QUOTE_NORMALISED) or invented (false even after it - it fails, logged
    loudly as SHADOW_QUOTE_INVENTED). The two never look the same: a guard that
    ate a true claim and a model that invented words are different failures.
  - THE CHECKS THAT BLOCK AT THE WRITE GATE (step 4) are named in BLOCKING. In
    shadow each turn records which claims and answers WOULD be blocked, so the
    block rate is known before the gate ships. A blocked item goes unresolved and
    the items beside it stand (R6).
  - A referent outside the closed set (something from an earlier turn) cannot be
    expressed: the figure goes to unresolved with why earlier_referent, counted
    apart from a misreading.
  - Every row carries its context_mode, so a context change is separable from a
    contract change (Cowork 1078: the version did not capture f215e8a0 vs 3d0a7065).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# v1.1 (Cowork 1062, 2026-09-14): a claim addresses a ROW (line AND product);
# the parts of each surface are named so span width is measured by position; a
# reason is never a claim; a text claim never repeats another claim's figure.
# v1.2: string fields classified, R2 against a stated normal form, blocking named.
# v1.3 (Cowork 1093): a range's value_number stays null - a PROMPT change, so the
# version moves and the window's rows stay separable.
# v1.4 (Nick ruled 2026-09-14): a quote is ONE contiguous span of HER message -
# stitched, altered and app-worded quotes fail like invented ones and are graded
# apart; the prompt says so, so the version moves.
# v1.5 (Nick ruled 2026-09-14): a fixed or moveable firmness carries its reason FROM
# HER MESSAGE - required, never borrowed from the app, never silently absent; with no
# words of hers for it, firmness is unknown. A prompt change, so the version moves.
# v1.6 (Cowork 1141, Nick's "next refinement"): firmness is for a limit; stance
# (directive / open) and support_surface carry the other three things it was holding.
CONTRACT_VERSION = "v1.6"
CONTEXT_MODE = "parity_last_assistant_only"
TABLE = "intake_turn_interpretations_shadow"
URL = "https://api.openai.com/v1/responses"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  turn INT NULL,
  message_sha256 CHAR(64) NULL,
  message_chars INT NULL,
  contract_version VARCHAR(16) NOT NULL,
  model VARCHAR(64) NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL,
  error TEXT NULL,
  elapsed_ms INT NULL,
  tokens_in INT NULL,
  tokens_out INT NULL,
  interpretation_json LONGTEXT NULL,
  quote_failures_json TEXT NULL,
  checks_json TEXT NULL,
  context_mode VARCHAR(48) NULL,
  claims_total INT NULL,
  claims_blocked INT NULL,
  source_draft_id VARCHAR(64) NULL,
  source_message_index INT NULL,
  checks_version VARCHAR(16) NULL,
  created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_draft_turn (draft_id, turn)
)
"""
# columns added after the table first shipped; a table created earlier gains them
_ADDED_COLUMNS = (
  ("checks_json", "TEXT NULL"),                 # v1.1
  ("context_mode", "VARCHAR(48) NULL"),         # v1.2
  ("claims_total", "INT NULL"),                 # v1.2
  ("claims_blocked", "INT NULL"),               # v1.2
  # v1.4 (Nick 2026-09-14, Cowork asked twice): a replayed or forced row names its
  # source by the WHOLE draft id and the message index, never an 8-char prefix
  ("source_draft_id", "VARCHAR(64) NULL"),
  ("source_message_index", "INT NULL"),
  # WHICH CHECKS SCORED THIS ROW (Cowork 1137): contract_version names the PROMPT;
  # a row replayed with an older module was scored by that module's checks, and
  # nothing said so. NULL = scored by checks that were not recorded.
  ("checks_version", "VARCHAR(16) NULL"),
)
_ensured = False
_lock = threading.Lock()

KINDS = ["ceiling", "actual", "typical", "concurrent", "cycle_time", "price", "cost", "count", "share", "date",
         "duration", "text", "choice", "identity"]
PERS = ["at_once", "day", "week", "month", "quarter", "year", "unit", "job", "none"]
OUTCOMES = ["accept", "decline", "choose", "provide", "close_list", "unsure", "asks_back"]
UNRESOLVED_WHY = ["which_line", "which_basis", "which_field", "earlier_referent", "unclear"]
# the kinds that are quantities OF A ROW - a figure of one of these must address its row
ROW_KINDS = ("ceiling", "actual", "typical", "concurrent", "cycle_time", "price")


def _nullable(t: str) -> Dict[str, Any]:
  return {"type": [t, "null"]}


def _obj(props: Dict[str, Any]) -> Dict[str, Any]:
  return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


SCHEMA: Dict[str, Any] = _obj({
  "claims": {"type": "array", "items": _obj({
    "id": {"type": "string"},
    "subject": {"type": "string"},
    "line": _nullable("string"),
    "product": _nullable("string"),
    "kind": {"type": "string", "enum": KINDS},
    "value_number": _nullable("number"),
    "value_low": _nullable("number"),
    "value_high": _nullable("number"),
    "value_text": _nullable("string"),
    "per": {"type": "string", "enum": PERS},
    "currency": _nullable("string"),
    "is_percent": {"type": "boolean"},
    "precision": {"type": "string", "enum": ["exact", "approximate"]},
    "surface": {"type": "string"},
    "value_surface": _nullable("string"),
    "unit_surface": _nullable("string"),
    "qualifier_surface": _nullable("string"),
    "polarity": {"type": "string", "enum": ["affirm", "negate"]},
    "firmness": {"type": "string", "enum": ["fixed", "moveable", "unknown"]},
    "firmness_direction": {"type": "string", "enum": ["up_only", "down_only", "both", "none"]},
    "firmness_reason_surface": _nullable("string"),
    # v1.6 (Cowork 1141): firmness is for a LIMIT; a directive, an open door and a
    # figure's backing are different things and get their own fields
    "stance": {"type": "string", "enum": ["none", "directive", "open"]},
    "stance_surface": _nullable("string"),
    "support_surface": _nullable("string"),
    "provenance": {"type": "string", "enum": ["stated", "agreed_to_proposal", "correction"]},
    "role": {"type": "string", "enum": ["answered", "alongside"]},
    "supersedes": _nullable("string"),
    "refers_to": {"type": "array", "items": {"type": "string"}},
  })},
  "answers": {"type": "array", "items": _obj({
    "question_quote": {"type": "string"},
    "outcome": {"type": "string", "enum": OUTCOMES},
    "option": _nullable("string"),
    "surface": {"type": "string"},
  })},
  "unresolved": {"type": "array", "items": _obj({
    "surface": {"type": "string"},
    "value_number": _nullable("number"),
    "why": {"type": "string", "enum": UNRESOLVED_WHY},
    "candidates": {"type": "array", "items": {"type": "string"}},
  })},
  "client_questions": {"type": "array", "items": _obj({"surface": {"type": "string"}})},
})

# EVERY STRING FIELD, CLASSIFIED (Nick ruled 2026-09-14). A pin walks SCHEMA and
# fails on a string field missing here, so a new one cannot ship unclassified.
#   quote_her  - copied from her message; checked against it (R2, normal form)
#   quote_app  - copied from the app's last message; checked against that
#   closed_set - an identity drawn from a set the app supplied (lines, claim ids,
#                ISO currency codes); never reaches a client as her words
#   machine    - the app's own vocabulary (a subject path); never reaches a
#                client, never carries a figure - checked for digits and number words
#   enum       - fixed by the schema
STRING_FIELDS: Dict[str, str] = {
  "claims.id": "closed_set",
  "claims.subject": "machine",
  "claims.line": "closed_set",
  "claims.product": "closed_set",
  "claims.kind": "enum",
  "claims.value_text": "quote_her",
  "claims.per": "enum",
  "claims.currency": "closed_set",
  "claims.precision": "enum",
  "claims.surface": "quote_her",
  "claims.value_surface": "quote_her",
  "claims.unit_surface": "quote_her",
  "claims.qualifier_surface": "quote_her",
  "claims.polarity": "enum",
  "claims.firmness": "enum",
  "claims.firmness_direction": "enum",
  "claims.firmness_reason_surface": "quote_her",
  "claims.stance": "enum",
  "claims.stance_surface": "quote_her",
  "claims.support_surface": "quote_her",
  "claims.provenance": "enum",
  "claims.role": "enum",
  "claims.supersedes": "machine",
  "claims.refers_to[]": "closed_set",
  "answers.question_quote": "quote_app",
  "answers.outcome": "enum",
  "answers.option": "quote_app",
  "answers.surface": "quote_her",
  "unresolved.surface": "quote_her",
  "unresolved.why": "enum",
  "unresolved.candidates[]": "machine",
  "client_questions.surface": "quote_her",
}

# THE CHECKS THAT BLOCK AT THE WRITE GATE (step 4). Each names the item it fails
# (claims[i] / answers[i]); that item goes unresolved and the rest stand (R6).
# A failed or unparseable interpretation writes nothing at all (R3).
BLOCKING = (
  "quote_failures",               # a quoted span not in its source even after the normal form - invented
  "subspan_failures",             # a value/unit/qualifier part not inside its own surface
  "figure_in_text_claim",         # a text claim repeating another claim's figure
  "reason_as_claim",              # a firmness reason stored as a claim of its own
  "row_outside_lines",            # line/product not a row the app supplied
  "row_missing",                  # a figure about an ops row with no row, when the app supplied rows
  "refers_to_outside_closed_set", # a referent that is not a claim id or a supplied line/product
  "figure_in_machine_field",      # a digit or number word in subject / supersedes / candidates
  "bad_ids",                      # an id that is not c1, c2, ... or is repeated
  "bad_currency",                 # a currency that is not a three-letter code
  "number_with_range",            # value_number beside value_low/value_high - a midpoint she never said
)
# recorded and logged, never blocking: a true quote after the normal form, a
# surface wider than its parts (the smallest-span rule, measured), a claim that
# contradicts itself on precision, and a fixed limit with no reason (Cowork 1098,
# measured on 808 archived claims: 2 self-contradicting, 41 of 103 fixed unreasoned)
RECORD_ONLY = ("quote_normalised", "span_excess_chars", "precision_contradicts_qualifier", "fixed_without_reason",
               "firmness_without_reason", "stance_without_words", "directive_off_figure")
# a qualifier that IS a hedge, as the whole of qualifier_surface (the contract's own
# output, not her sentence): with one of these, precision cannot be exact
_HEDGE_QUALIFIER_RE = re.compile(r"^\s*(about|around|roughly|approximately|approx\.?|usually|typically|most weeks|"
                                 r"or so|give or take|something like|close to|nearly|almost)\s*$", re.I)

SYSTEM = (
  "You interpret ONE message a small-business owner has just sent, for a planning intake. You do not reply to her "
  "and you do not decide what the app does next. You record what she said, claim by claim, so nothing else ever has "
  "to read her words again.\n\n"
  "CLAIMS - one per fact she stated. A sentence can hold several; record every one, including facts she volunteered "
  "beside the answer (role alongside) as well as the answer itself (role answered).\n"
  "- id: c1, c2, c3 ... in order. A label, never a figure.\n"
  "- subject: what the fact is about, in the app's terms where one fits (for example ops.capacity, ops.price, "
  "financials.rent, people.headcount, business.legal_entity), otherwise a short plain phrase. A subject NEVER "
  "carries a figure or a number word - the figure goes in value.\n"
  "- line and product: the ROW it is about. line is a line_of_business and product a product, each copied exactly "
  "from `lines`. Null for both when it is about the whole business. When she names a line that holds several products "
  "and does not say which one, do NOT pick one: put the figure in unresolved with why which_line.\n"
  "- kind: ceiling (the most possible - 'flat out', 'the most we could'), actual (what really happens - 'in practice', "
  "'we usually finish'), typical (a usual figure or range), concurrent (how many at once), cycle_time (how long one "
  "takes), price, cost, count, share, date, duration, text, choice, identity.\n"
  "- value: value_number for one figure; value_low and value_high for a range ('five or six' is 5 to 6, never 5.5) - "
  "and for a range value_number stays null; "
  "value_text for a fact that is not a number. Write numbers as she meant them ('three hundred and forty' is 340; "
  "'1.2 million' is 1200000).\n"
  "- value_text is HER WORDS, copied character for character from her message - never a paraphrase, a summary or a "
  "tidied version.\n"
  "- per: what it is per - at_once, day, week, month, quarter, year, unit, job, or none. 'Six at once' is at_once; "
  "'480 a week' is week; 'ten weeks per frame' is kind cycle_time, per unit.\n"
  "- currency: a three-letter code such as USD, or null.\n"
  "- precision: approximate when she hedged (about, around, roughly, most weeks), else exact.\n"
  "- SURFACE, BY RULE: the smallest contiguous span of HER MESSAGE that contains the value AND its unit or denominator "
  "AND any qualifier, copied character for character - same spelling, same case, same punctuation, spelled numbers "
  "left spelled. Not a paraphrase, not a summary, not a span you shorten to look tidy. It is ONE unbroken stretch "
  "of her message: never words joined across a gap, never with words dropped from the middle or an ellipsis, and "
  "never words from the app's message - those are not her sentence. If the value, unit and "
  "qualifier are far apart, the span runs from the first to the last of them.\n"
  "- value_surface, unit_surface, qualifier_surface: the exact words inside surface that carry the value, the unit or "
  "denominator, and the qualifier - each copied character for character, null when there is none. Each is ONE "
  "contiguous stretch you SELECT from inside surface as it stands - never surface with the value or unit deleted from "
  "it. When her unit is split by the value ('sessions above 40 per week'), unit_surface is the one stretch that carries "
  "the denominator ('per week'), never the two halves joined. surface starts at "
  "the first of them and ends at the last; words before the first or after the last do not belong in surface.\n"
  "- A REASON IS NEVER A CLAIM OF ITS OWN: it goes in firmness_reason_surface of the claim it limits. A text claim "
  "never repeats a figure that is already the value of another claim.\n"
  "- polarity: negate for a fact stated as absence or refusal ('we have never borrowed', 'we hardly ever deal with "
  "homeowners'). A no is a fact, not a missing value.\n"
  "- firmness: fixed when she says it cannot move and why ('that's the building', 'the accreditation caps us'), "
  "moveable when she says it can; direction up_only / down_only when she limits only one way.\n"
  "- firmness_reason_surface is REQUIRED whenever firmness is fixed or moveable: the ONE contiguous stretch of HER "
  "message that gives her reason or states the limit in her own words ('We're not planning to change the team size "
  "right now', 'that's the building'). Never borrow a reason from the app's message. If her message neither gives a "
  "reason nor states the limit, firmness is unknown - a limit is fixed or moveable only on her own words.\n"
  "- firmness is for a LIMIT only. Three other things are NOT limits and have their own fields:\n"
  "  - stance directive: she instructs which figure or choice the plan must use ('please use the $500,000 figure for "
  "planning'). Record it ON the claim that holds that figure - never as a claim of its own.\n"
  "  - stance open: she marks something as not settled ('for now', 'we may add someone later').\n"
  "  - stance is none otherwise. stance_surface is her words for the stance, one contiguous stretch of her message, "
  "required whenever stance is not none.\n"
  "  - support_surface: her words that back up a figure without limiting it ('None of us have reduced hours or changed "
  "roles', said of a payroll figure), on the claim they support; null when there are none.\n"
  "- provenance: stated; agreed_to_proposal when she is agreeing to a figure the app proposed in its last message; "
  "correction when she is correcting something - then supersedes is the SUBJECT of the fact it replaces (for example "
  "ops.capacity), never a figure.\n"
  "- refers_to: what a pronoun or 'the other one' points at - ONLY a claim id from this interpretation, or a "
  "line_of_business or product name copied exactly from `lines`. Nothing else. When what she points at is neither "
  "(something from an earlier message), do not guess: put the figure in unresolved with why earlier_referent.\n"
  "NEVER COMPUTE. A ratio, a share, turns per year, a monthly figure from a yearly one - none of these is a claim. "
  "Record only what she said; the app does the arithmetic.\n\n"
  "ANSWERS - for each question in the app's last message that her message answers: question_quote copied verbatim "
  "from that message, and an outcome: accept, DECLINE, choose, provide, close_list ('that's everyone'), "
  "unsure, asks_back. For choose, option is the option's words copied verbatim from the app's last message. A "
  "decline is an answer, not the absence of one.\n\n"
  "UNRESOLVED - a figure you cannot place with confidence (which line, which basis, which field, or an earlier "
  "referent): its surface, its value, why, and candidate subjects (never figures). An honest gap is better than a "
  "confident wrong claim.\n\n"
  "CLIENT_QUESTIONS - anything she asked, as its surface.\n\n"
  "If her message states nothing, return empty lists."
)


def enabled() -> bool:
  return (os.getenv("INTAKE_SHADOW_INTERPRETATION") or "").strip().lower() in ("1", "true", "on", "yes")


def _connect():
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  return get_mysql_connection()


def _post(**kw):
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore
  return post_openai_with_retries(**kw)


def _ensure(conn) -> None:
  global _ensured
  if _ensured:
    return
  with _lock:
    if _ensured:
      return
    cur = conn.cursor()
    try:
      cur.execute(_DDL)
      for col, decl in _ADDED_COLUMNS:
        # errno 1060 = the column is already there
        try:
          cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {decl}")
        except Exception as exc:
          if getattr(exc, "errno", None) != 1060:
            raise
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
    _ensured = True


def _strip_private(obj: Any) -> Any:
  if isinstance(obj, dict):
    return {k: _strip_private(v) for k, v in obj.items() if not str(k).startswith("_")}
  if isinstance(obj, list):
    return [_strip_private(v) for v in obj]
  return obj


def build_input(*, message: str, messages: List[Dict[str, Any]], sections: Dict[str, Any], focus: str,
                confirm_question: str) -> str:
  """The shadow's whole input, serialised NOW - on the request thread, before the
  turn mutates anything - so it reads what the real turn reads at the same point.

  CONTEXT PARITY WITH THE LIVE ROUTER (Cowork 1055, 2026-09-14): the router is
  given the app's LAST MESSAGE only, plus the draft state. The shadow gets the same
  history, so a disagreement measures the contract, not a difference in context.
  A prior-claims digest, when it comes, is a separate labelled change."""
  convo = [m for m in (messages or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
  last_assistant = next((str(m.get("content") or "") for m in reversed(convo) if m.get("role") == "assistant"), "")
  lines = []
  for lm in ((sections or {}).get("ops") or {}).get("lob_models") or []:
    for p in (lm or {}).get("products") or []:
      if isinstance(p, dict):
        lines.append({"line_of_business": lm.get("lob_name"), "product": p.get("product_name"),
                      "cadence": p.get("unit_cadence")})
  body = {
    "message": str(message or ""),
    "last_assistant_message": last_assistant,
    "context": CONTEXT_MODE,
    "focus": focus,
    "confirm_question": confirm_question or "",
    "lines": lines,
    "known_facts": _strip_private(sections or {}),
  }
  return json.dumps(body, ensure_ascii=False, default=str)


# THE STATED NORMAL FORM (R2, Nick ruled 2026-09-14). Applied to BOTH the quote
# and its source before the second comparison, and nothing else: Unicode NFC;
# typographic single quotes and primes to ' ; typographic double quotes to " ;
# every hyphen and dash (non-breaking hyphen, en, em, minus...) to - ; the
# ellipsis character to ... ; every run of whitespace (no-break spaces included)
# to one space; ends trimmed. Case, spelling, digits, commas and word order are
# NOT normalised - a quote that differs in any of those is invented.
_NF_TABLE = {ord(c): "'" for c in "‘’‚‛′"}
_NF_TABLE.update({ord(c): '"' for c in "“”„‟″"})
_NF_TABLE.update({ord(c): "-" for c in "‐‑‒–—―−"})
_NF_TABLE[ord("…")] = "..."
_WS_RE = re.compile(r"\s+")


def normal_form(s: Any) -> str:
  return _WS_RE.sub(" ", unicodedata.normalize("NFC", str(s or "")).translate(_NF_TABLE)).strip()


# A QUOTE IS A CONTIGUOUS SPAN OF HER MESSAGE (Nick ruled 2026-09-14). Only the
# first two grades pass. The failures are graded apart so it can be seen which is
# happening - and a stitched quote fails exactly as an invented one does: her own
# vocabulary in an order she never used is what a client nods at in a readback.
QUOTE_PASS = ("exact", "normalised")
QUOTE_FAIL = ("altered", "stitched", "app_words", "invented")


def _tokens(s: Any) -> List[str]:
  """The words of a normal-formed string, edge punctuation stripped; a piece with
  no letter or digit (an ellipsis, a dash) is not a word."""
  out = []
  for t in normal_form(s).split(" "):
    t = t.strip(".,;:!?\"'()[]{}")
    if t and re.search(r"\w", t):
      out.append(t)
  return out


def _ordered_in(span_toks: List[str], src_toks: List[str]) -> tuple:
  """(found in order, found as one unbroken run). Compared without case: this only
  NAMES a failure - her sentence with one capital lowered is her words altered,
  not invented (Ferriday & Blythe 73a71cfea4244c69a6ebe85181198f34 msg 95). A
  quote still only PASSES exactly or after the normal form, case untouched."""
  span_toks = [t.casefold() for t in span_toks]
  src_toks = [t.casefold() for t in src_toks]
  n = len(span_toks)
  if not n:
    return False, False
  for k in range(len(src_toks) - n + 1):
    if src_toks[k:k + n] == span_toks:
      return True, True
  j = 0
  for t in src_toks:
    if j < n and t == span_toks[j]:
      j += 1
  return j == n, False


def quote_grade(span: Any, source: Any, app_source: Any = None) -> str:
  """The span is searched in SOURCE (her message) only; app_source (the app's last
  message) is consulted solely to NAME a failure, never to pass one.
    exact      - in her message as it stands                               (pass)
    normalised - in her message after the stated normal form               (pass)
    app_words  - the APP's words quoted as hers - worse than invention     (fail)
    altered    - her words as one unbroken run, punctuation or case changed (fail)
    stitched   - her words in her order, joined across a gap               (fail)
    invented   - anything else; an empty quote too                         (fail)
  Case is never folded for a PASS: a changed capital fails. It is folded only to
  name which failure happened."""
  span, source = str(span or ""), str(source or "")
  if span and span in source:
    return "exact"
  nf = normal_form(span)
  if nf and nf in normal_form(source):
    return "normalised"
  if app_source and nf and nf.casefold() in normal_form(app_source).casefold():
    return "app_words"
  toks = _tokens(span)
  if toks:
    found, unbroken = _ordered_in(toks, _tokens(source))
    if found and unbroken:
      return "altered"
    if found and len(toks) >= 2:
      return "stitched"
    if app_source and len(toks) >= 2 and _ordered_in(toks, _tokens(app_source))[0]:
      return "app_words"
  return "invented"


def _quoted_spans(interpretation: Dict[str, Any]) -> List[tuple]:
  """(path, span, source) for every quoted string the interpretation holds.
  source is 'her' or 'app'. A required surface is checked even when empty; an
  optional quote is checked only when present."""
  interp = interpretation or {}
  out: List[tuple] = []
  for group in ("claims", "answers", "unresolved", "client_questions"):
    for i, item in enumerate(interp.get(group) or []):
      item = item if isinstance(item, dict) else {}
      out.append(("%s[%d]" % (group, i), item.get("surface"), "her"))
      if group == "claims":
        for part in ("value_surface", "unit_surface", "qualifier_surface", "firmness_reason_surface", "stance_surface",
                     "support_surface", "value_text"):
          if item.get(part):
            out.append(("claims[%d].%s" % (i, part), item.get(part), "her"))
      if group == "answers":
        out.append(("answers[%d].question_quote" % i, item.get("question_quote"), "app"))
        if item.get("option"):
          out.append(("answers[%d].option" % i, item.get("option"), "app"))
  return out


def quote_grades(interpretation: Dict[str, Any], message: str, app_message: str = "") -> Dict[str, List[str]]:
  """Every quoted path, by grade. Her quotes are searched in HER message only (the
  app's message may only name the failure); the app-side quotes (question_quote,
  option) are searched in the app's message."""
  grades: Dict[str, List[str]] = {g: [] for g in QUOTE_PASS + QUOTE_FAIL}
  for path, span, source in _quoted_spans(interpretation):
    if source == "her":
      g = quote_grade(span, message, app_source=app_message or None)
    else:
      g = quote_grade(span, app_message)
    grades[g].append(path)
  return grades


def _app_side(path: str) -> bool:
  return ".question_quote" in path or ".option" in path


def quote_failures(interpretation: Dict[str, Any], message: str, app_message: Optional[str] = None) -> List[str]:
  """R2: every quoted span must be ONE contiguous span of its source - exactly, or
  after the stated normal form. Returned: every failing path, whatever its grade
  (altered, stitched, app_words, invented). Without an app message the app-side
  quotes are not judged (nothing to judge them against)."""
  grades = quote_grades(interpretation, message, app_message or "")
  failed = [p for g in QUOTE_FAIL for p in grades[g]]
  if app_message is None:
    failed = [p for p in failed if not _app_side(p)]
  return failed


def _figure_strings(v: Any) -> List[str]:
  try:
    f = float(v)
  except (TypeError, ValueError):
    return []
  out = {"%g" % f}
  if f == int(f):
    out.add(str(int(f)))
    out.add(format(int(f), ","))
  return [s for s in out if s]


_NUMBER_WORD_RE = re.compile(
  r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
  r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
  r"billion|dozen|half)\b", re.I)


def _carries_figure(s: Any) -> bool:
  """A figure in a machine field: a whole token that is a number of 10 or more
  (optionally with k/m), or a number word. The app's own identifiers are not
  figures - marketing_total_year1 and q1 carry a digit inside a name, owner_1 an
  ordinal (measured on 166 archived sentences: 55 of 59 flags were those).
  Named limit: a single-digit figure standing alone in a subject is not caught."""
  s = str(s or "")
  for tok in re.split(r"[\s._\-\[\]/:,]+", s):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmM])?", tok)
    if m and (m.group(2) or float(m.group(1)) >= 10):
      return True
  return bool(_NUMBER_WORD_RE.search(s))


def contract_checks(interpretation: Dict[str, Any], message: str, app_message: Optional[str] = None,
                    lines: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
  """Checks on the contract's OWN OUTPUT (Cowork 1062, Nick 2026-09-14). None of
  them reads her words for meaning: they are string presence, string position and
  membership of a closed set.
    quote_failures       - every quoted span that is not ONE contiguous span of its source (blocks)
    quote_altered / quote_stitched / quote_app_words / quote_invented - the same failures by grade
    quote_normalised     - a quoted span in its source only after the normal form (passes; logged)
    subspan_failures     - a value/unit/qualifier part not verbatim inside its surface
    span_excess_chars    - characters of surface outside the stretch from its first
                           named part to its last (the smallest-span rule, measured)
    figure_in_text_claim - a text claim whose value_text repeats, in digits, the value
                           of a numeric claim in the same interpretation
    reason_as_claim      - a text claim that repeats another claim's firmness reason
    row_outside_lines    - a line or product that is not a row in `lines`
    row_missing          - a figure about an ops.* subject with no line or product, when rows exist
    refers_to_outside_closed_set - a referent not a claim id here nor a supplied line/product
    figure_in_machine_field - a digit or number word in subject, supersedes or candidates
    bad_ids / bad_currency  - an id not c1, c2 ... or repeated; a currency not three letters
    blocked              - the claims[i] / answers[i] a BLOCKING check names (would not write)
    unexpressible_referents - unresolved items whose why is earlier_referent
  Row checks run only when `lines` is given. Named limit: a repeated figure spelled
  out in words is not caught by figure_in_text_claim."""
  interp = interpretation or {}
  claims = [c if isinstance(c, dict) else {} for c in (interp.get("claims") or [])]
  grades = quote_grades(interp, message, app_message or "")
  if app_message is None:
    grades = {g: [p for p in paths if not _app_side(p)] for g, paths in grades.items()}
  checks: Dict[str, Any] = {"quote_failures": [p for g in QUOTE_FAIL for p in grades[g]],
                            "quote_normalised": grades["normalised"], "quote_altered": grades["altered"],
                            "quote_stitched": grades["stitched"], "quote_app_words": grades["app_words"],
                            "quote_invented": grades["invented"], "subspan_failures": [],
                            "span_excess_chars": {}, "figure_in_text_claim": [], "reason_as_claim": [],
                            "row_outside_lines": [], "row_missing": [], "refers_to_outside_closed_set": [],
                            "figure_in_machine_field": [], "bad_ids": [], "bad_currency": [],
                            "number_with_range": [], "precision_contradicts_qualifier": [],
                            "fixed_without_reason": [], "firmness_without_reason": [],
                            "stance_without_words": [], "directive_off_figure": []}
  for i, c in enumerate(claims):
    # PARTS ARE FOUND IN THE NORMAL FORM TOO (forced 2026-09-14): a surface the
    # normal form had to rescue, whose parts kept her curly quote, failed here
    # instead - the guard eating a true claim through a second door. Positions
    # and width are measured on the normal forms.
    surface = normal_form(c.get("surface"))
    positions = []
    for part in ("value_surface", "unit_surface", "qualifier_surface"):
      p = normal_form(c.get(part)) if c.get(part) else ""
      if not p:
        continue
      at = surface.find(str(p))
      if at < 0:
        checks["subspan_failures"].append("claims[%d].%s" % (i, part))
      else:
        positions.append((at, at + len(str(p))))
    if positions:
      start, end = min(a for a, _ in positions), max(b for _, b in positions)
      excess = len(surface) - (end - start)
      if excess > 0:
        checks["span_excess_chars"]["claims[%d]" % i] = excess
  figures = set()
  for c in claims:
    for key in ("value_number", "value_low", "value_high"):
      if c.get(key) is not None:
        figures.update(_figure_strings(c.get(key)))
  reasons = [(k, str(c.get("firmness_reason_surface")).strip()) for k, c in enumerate(claims)
             if c.get("firmness_reason_surface")]
  for i, c in enumerate(claims):
    text = c.get("value_text")
    if not text or c.get("value_number") is not None:
      continue
    text = str(text)
    if any(f in text for f in figures):
      checks["figure_in_text_claim"].append("claims[%d]" % i)
    stripped = text.strip()
    # ANOTHER claim's reason: a claim is never a copy of a reason it carries itself
    if any(stripped and (stripped in r or r in stripped) for k, r in reasons if r and k != i):
      checks["reason_as_claim"].append("claims[%d]" % i)

  ids = [str(c.get("id") or "") for c in claims]
  for i, cid in enumerate(ids):
    if not re.fullmatch(r"c[1-9]\d*", cid) or ids.count(cid) > 1:
      checks["bad_ids"].append("claims[%d]" % i)
  for i, c in enumerate(claims):
    # ONE COPY OF A QUANTITY (Cowork 1093): Isadora's "five or six" came back as
    # 5 to 6 AND value_number 5.5 - a figure she never said, in the field a writer
    # reaches for first. A range is low and high; the single value stays null.
    if c.get("value_low") is not None and c.get("value_high") is not None and c.get("value_number") is not None:
      checks["number_with_range"].append("claims[%d]" % i)
    # the claim contradicts itself: its own qualifier is a hedge and its precision says exact
    if c.get("precision") == "exact" and _HEDGE_QUALIFIER_RE.match(str(c.get("qualifier_surface") or "")):
      checks["precision_contradicts_qualifier"].append("claims[%d]" % i)
    # a limit she called fixed carries the reason that makes it defensible later
    if c.get("firmness") == "fixed" and not str(c.get("firmness_reason_surface") or "").strip():
      checks["fixed_without_reason"].append("claims[%d]" % i)
    # v1.5 (Nick 2026-09-14): ANY firmness - fixed or moveable - needs her reason; a
    # limit with no words of hers behind it cannot be defended when coherence later
    # offers to move it (the Sablecreek lease shape). Recorded: the figure is still hers.
    if c.get("firmness") in ("fixed", "moveable") and not str(c.get("firmness_reason_surface") or "").strip():
      checks["firmness_without_reason"].append("claims[%d]" % i)
    # v1.6 (Cowork 1141): a directive or an open door stands on her words...
    if c.get("stance") in ("directive", "open") and not str(c.get("stance_surface") or "").strip():
      checks["stance_without_words"].append("claims[%d]" % i)
    # ...and a directive about a figure sits ON that figure's claim. Bright Smiles
    # msg 67: "please use the $500,000 figure for planning" became a separate choice
    # claim while 500,000 sat in another - the instruction was never on the number.
    if c.get("stance") == "directive" and all(c.get(k) is None for k in ("value_number", "value_low", "value_high")):
      _dtext = " ".join(str(c.get(k) or "") for k in ("stance_surface", "value_text", "surface"))
      if any(f and f in _dtext for f in figures if len(f.replace(",", "").replace(".", "")) >= 2):
        checks["directive_off_figure"].append("claims[%d]" % i)
    cur = c.get("currency")
    if cur is not None and not re.fullmatch(r"[A-Z]{3}", str(cur)):
      checks["bad_currency"].append("claims[%d]" % i)
    for field in ("subject", "supersedes"):
      if _carries_figure(c.get(field)):
        checks["figure_in_machine_field"].append("claims[%d].%s" % (i, field))
  for i, u in enumerate(interp.get("unresolved") or []):
    for j, cand in enumerate((u or {}).get("candidates") or []):
      if _carries_figure(cand):
        checks["figure_in_machine_field"].append("unresolved[%d].candidates[%d]" % (i, j))

  if lines is not None:
    rows = [(str((r or {}).get("line_of_business") or ""), str((r or {}).get("product") or "")) for r in lines]
    names = {n for pair in rows for n in pair if n}
    valid_ids = {cid for cid in ids if re.fullmatch(r"c[1-9]\d*", cid)}
    products = Counter(p for _, p in rows if p)
    by_line = Counter(l for l, _ in rows if l)
    for i, c in enumerate(claims):
      line, product = c.get("line"), c.get("product")
      addressed = False
      # a row is ADDRESSED by its (line, product) pair, by a product name that
      # is unique among the rows, or by a line that holds exactly one product
      if product is not None and line is None:
        addressed = products.get(str(product)) == 1
        if not addressed:
          checks["row_outside_lines"].append("claims[%d]" % i)
      elif product is not None and (str(line), str(product)) not in rows:
        checks["row_outside_lines"].append("claims[%d]" % i)
      elif product is None and line is not None:
        addressed = by_line.get(str(line)) == 1
        if str(line) not in by_line:
          checks["row_outside_lines"].append("claims[%d]" % i)
      else:
        addressed = product is not None
      for j, ref in enumerate(c.get("refers_to") or []):
        if str(ref) not in valid_ids and str(ref) not in names:
          checks["refers_to_outside_closed_set"].append("claims[%d].refers_to[%d]" % (i, j))
      # AN EMPTY ROW IS NOT A RIGHT ROW (Cowork 1089): a figure about an ops row
      # that names no line and product would otherwise pass row_outside_lines by
      # being null - the empty-is-not-wrong shape. Only when the app supplied rows.
      # Row quantities only - capacity, volume, cycle time, price - by KIND, the
      # enum, not by the free subject: business-wide ops costs and options carry
      # no row (measured: the ops.* prefix alone flagged running costs and picks).
      numeric = any(c.get(k) is not None for k in ("value_number", "value_low", "value_high"))
      if rows and numeric and c.get("kind") in ROW_KINDS and str(c.get("subject") or "").startswith("ops.") \
          and not addressed and "claims[%d]" % i not in checks["row_outside_lines"]:
        checks["row_missing"].append("claims[%d]" % i)

  blocked = set()
  for name in BLOCKING:
    for path in checks.get(name) or []:
      root = re.match(r"(claims|answers)\[\d+\]", str(path))
      if root:
        blocked.add(root.group(0))
  checks["blocked"] = sorted(blocked, key=lambda p: (p.split("[")[0], int(re.search(r"\d+", p).group(0))))
  checks["claims_total"] = len(claims)
  checks["claims_blocked"] = sum(1 for p in blocked if p.startswith("claims["))
  checks["unexpressible_referents"] = sum(1 for u in (interp.get("unresolved") or [])
                                          if isinstance(u, dict) and u.get("why") == "earlier_referent")
  return checks


def _parse(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  for item in (data or {}).get("output") or []:
    for part in (item or {}).get("content") or []:
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


def run(*, draft_id: str, turn: int, message: str, input_json: str, source_draft_id: Optional[str] = None,
        source_message_index: Optional[int] = None) -> Dict[str, Any]:
  """One shadow interpretation, recorded. Never raises. A replay of an archived
  sentence names its source by the whole draft id and message index."""
  model = (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"
  t0 = time.monotonic()
  row: Dict[str, Any] = {"draft_id": draft_id, "turn": turn, "status": "error", "error": None, "model": model,
                         "interpretation": None, "quote_failures": [], "checks": None, "tokens_in": None,
                         "tokens_out": None, "context_mode": None, "source_draft_id": source_draft_id,
                         "source_message_index": source_message_index}
  try:
    try:
      body = json.loads(input_json or "{}")
    except Exception:
      body = {}
    row["context_mode"] = body.get("context")
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
      raise RuntimeError("no OPENAI_API_KEY")
    payload = {
      "model": model,
      "input": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": input_json}],
      "text": {"format": {"type": "json_schema", "name": "intake_interpretation_v1", "schema": SCHEMA,
                          "strict": True}},
    }
    resp = _post(url=URL, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                 payload=payload, timeout_seconds=float(os.getenv("INTAKE_SHADOW_TIMEOUT_SECONDS") or 60),
                 retryable_status=(429, 500, 502, 503, 504), max_attempts=2)
    if getattr(resp, "status_code", 500) >= 400:
      raise RuntimeError("HTTP %s: %s" % (resp.status_code, str(getattr(resp, "text", ""))[:300]))
    data = resp.json()
    usage = data.get("usage") or {}
    row["tokens_in"], row["tokens_out"] = usage.get("input_tokens"), usage.get("output_tokens")
    parsed = _parse(data)
    if parsed is None:
      raise RuntimeError("no parseable interpretation in the response")
    row["interpretation"] = parsed
    row["checks"] = contract_checks(parsed, message, app_message=str(body.get("last_assistant_message") or ""),
                                    lines=body.get("lines") if isinstance(body.get("lines"), list) else [])
    row["quote_failures"] = row["checks"]["quote_failures"]
    row["status"] = "ok"
    # LOUD, AND NEVER ALIKE (Nick 2026-09-14): each failing grade has its own tag,
    # and a true quote the normal form had to rescue has another
    for _grade in QUOTE_FAIL:
      if row["checks"].get("quote_" + _grade):
        logger.error("SHADOW_QUOTE_%s draft=%s turn=%s items=%s", _grade.upper(), draft_id, turn,
                     row["checks"]["quote_" + _grade])
    if row["checks"]["quote_normalised"]:
      logger.warning("SHADOW_QUOTE_NORMALISED draft=%s turn=%s items=%s", draft_id, turn,
                     row["checks"]["quote_normalised"])
  except Exception as exc:  # noqa: BLE001 - shadow failures are recorded, never raised
    row["error"] = ("%s: %s" % (type(exc).__name__, exc))[:2000]
  row["elapsed_ms"] = int((time.monotonic() - t0) * 1000.0)
  _record(row, message)
  return row


def _record(row: Dict[str, Any], message: str) -> None:
  checks = row.get("checks") or {}
  try:
    conn = _connect()
    try:
      _ensure(conn)
      cur = conn.cursor()
      try:
        cur.execute(
          f"INSERT INTO {TABLE} (draft_id, turn, message_sha256, message_chars, contract_version, model, status, error, "
          "elapsed_ms, tokens_in, tokens_out, interpretation_json, quote_failures_json, checks_json, context_mode, "
          "claims_total, claims_blocked, source_draft_id, source_message_index, checks_version) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
          (row["draft_id"], row["turn"], hashlib.sha256(str(message or "").encode("utf-8")).hexdigest(),
           len(str(message or "")), CONTRACT_VERSION, row["model"], row["status"], row["error"], row["elapsed_ms"],
           row["tokens_in"], row["tokens_out"],
           json.dumps(row["interpretation"], ensure_ascii=False) if row["interpretation"] is not None else None,
           json.dumps(row["quote_failures"]),
           json.dumps(row["checks"]) if row.get("checks") is not None else None,
           row.get("context_mode"), checks.get("claims_total"), checks.get("claims_blocked"),
           row.get("source_draft_id"), row.get("source_message_index"),
           CHECKS_VERSION if row.get("checks") is not None else None))
        try:
          conn.commit()
        except Exception:
          pass
      finally:
        cur.close()
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:  # noqa: BLE001
    logger.error("SHADOW_INTERPRETATION_WRITE_FAILED draft=%s turn=%s: %s", row.get("draft_id"), row.get("turn"), exc)


def start(*, draft_id: str, turn: int, message: str, messages: List[Dict[str, Any]], sections: Dict[str, Any],
          focus: str, confirm_question: str) -> Optional[threading.Thread]:
  """Start the shadow for this turn, or do nothing. The input is snapshotted here;
  the per-run identity (draft, for the response cache and usage ledger) is carried
  into the thread with a copied context."""
  if not enabled() or not str(message or "").strip() or not str(draft_id or "").strip():
    return None
  input_json = build_input(message=message, messages=messages, sections=sections, focus=focus,
                           confirm_question=confirm_question)
  ctx = contextvars.copy_context()
  th = threading.Thread(target=ctx.run, args=(run,),
                        kwargs={"draft_id": str(draft_id), "turn": turn, "message": str(message), "input_json": input_json},
                        name="shadow-interp-%s-%s" % (str(draft_id)[:8], turn), daemon=True)
  th.start()
  return th


def for_draft(conn, draft_id: str) -> List[Dict[str, Any]]:
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(f"SELECT id, turn, message_chars, contract_version, context_mode, model, status, error, elapsed_ms, "
                f"tokens_in, tokens_out, claims_total, claims_blocked, source_draft_id, source_message_index, "
                f"checks_version, interpretation_json, quote_failures_json, "
                f"checks_json, created_at FROM {TABLE} WHERE draft_id=%s ORDER BY id", (str(draft_id),))
    out = []
    for r in cur.fetchall():
      row = dict(r)
      for src, dst in (("interpretation_json", "interpretation"), ("quote_failures_json", "quote_failures"),
                       ("checks_json", "checks")):
        raw = row.pop(src, None)
        try:
          row[dst] = json.loads(raw) if raw else None
        except Exception:
          row[dst] = raw
      out.append(row)
    return out
  finally:
    cur.close()


def _like_prefix(prefix: str) -> str:
  """A LITERAL prefix for SQL LIKE. Unescaped, the '_' in 'br_' is a one-character
  wildcard, so 'br_' also matched every 'br14_' row (Cowork 1128: 180, not 168)."""
  p = str(prefix or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
  return p + "%"


def replays(conn, prefix: str = "") -> List[Dict[str, Any]]:
  """Every replayed or forced shadow row (draft_id not a real draft), with the WHOLE
  source draft id and message index, so a reader can fetch her actual message, and
  the version of the checks that scored it."""
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(f"SELECT id, draft_id, turn, source_draft_id, source_message_index, contract_version, checks_version, "
                f"status, claims_total, claims_blocked, created_at FROM {TABLE} "
                f"WHERE source_draft_id IS NOT NULL AND draft_id LIKE %s ORDER BY id", (_like_prefix(prefix),))
    return [dict(r) for r in cur.fetchall()]
  finally:
    cur.close()


def rescored(conn, prefix: str) -> List[Dict[str, Any]]:
  """Every replay row in a family scored by TODAY's checks (CHECKS_VERSION), beside the
  score it was stored with and the checks version that produced that - so a rate read
  from stored rows can never silently mix two sets of checks (Cowork 1137). The input
  is rebuilt from the source draft exactly as the replay built it."""
  rows = replays(conn, prefix)
  cur = conn.cursor(dictionary=True)
  out: List[Dict[str, Any]] = []
  drafts: Dict[str, Any] = {}
  J = lambda v: json.loads(v) if isinstance(v, str) and v else (v or {})
  try:
    for r in rows:
      cur.execute(f"SELECT interpretation_json, checks_json FROM {TABLE} WHERE id=%s", (r["id"],))
      x = cur.fetchone() or {}
      it = J(x.get("interpretation_json"))
      stored = J(x.get("checks_json"))
      sid, n = r["source_draft_id"], r["source_message_index"]
      if sid not in drafts:
        cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (sid,))
        drafts[sid] = cur.fetchone()
      d = drafts[sid]
      rec = {"id": r["id"], "draft_id": r["draft_id"], "contract_version": r["contract_version"],
             "source_draft_id": sid, "source_message_index": n, "status": r["status"],
             "stored": {"checks_version": r.get("checks_version"), "claims_total": stored.get("claims_total"),
                        "claims_blocked": stored.get("claims_blocked")}}
      if not d or not it or n is None:
        rec["today"] = None
        out.append(rec)
        continue
      msgs = J(d.get("messages_json"))
      sections = {"business": {"business_name": d.get("business_name")}, "ops": J(d.get("operating_model_json")),
                  "market": J(d.get("target_market_json")), "people": J(d.get("people_json")),
                  "financials": J(d.get("financials_json"))}
      body = json.loads(build_input(message=msgs[n]["content"], messages=msgs[:n], sections=sections,
                                    focus=str(d.get("active_focus") or ""), confirm_question=""))
      ch = contract_checks(it, body["message"], app_message=body["last_assistant_message"], lines=body["lines"])
      rec["today"] = {"checks_version": CHECKS_VERSION, "claims_total": ch["claims_total"],
                      "claims_blocked": ch["claims_blocked"], "blocked": ch["blocked"],
                      **{k: ch[k] for k in BLOCKING if ch.get(k)},
                      **{"quote_" + g: ch["quote_" + g] for g in QUOTE_FAIL if ch.get("quote_" + g)}}
      out.append(rec)
    return out
  finally:
    cur.close()


def _checks_version() -> str:
  """A fingerprint of the checks themselves - their source and their lists - so it
  moves whenever any check changes, with no one having to remember to bump it."""
  import inspect
  parts = [inspect.getsource(f) for f in (normal_form, _tokens, _ordered_in, quote_grade, quote_grades, quote_failures,
                                         _carries_figure, contract_checks)]
  parts.append(repr((BLOCKING, RECORD_ONLY, QUOTE_PASS, QUOTE_FAIL, ROW_KINDS, sorted(_NF_TABLE.items()))))
  return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:12]


CHECKS_VERSION = _checks_version()
