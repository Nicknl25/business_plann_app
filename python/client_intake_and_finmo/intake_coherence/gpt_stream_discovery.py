"""PROACTIVE STREAM DISCOVERY (docs/STREAM_DISCOVERY_SPEC.md, Nick-approved
2026-08-15, build authorized at neighbor-check tier).

THE MANDATE: surface revenue streams the client's business TYPE usually
has but the client never mentioned, so real revenue is not left out of
the plan. DISCOVERY not upsell; EXISTENCE not addition; only streams
genuinely common for THIS type (band-judged, NEVER a count); ask ONCE
and believe the answer; a yes lands as a real product row through the
ordinary ops capture (its five fields are asked by the same cascade
that asks every row - no number is ever estimated for it).

THE FENCE (the demand-judge pattern, applied to a category question):
  1. PYTHON decides evidence, never GPT: stream_discovery_evidence_level
     is THIN when business_type is missing, NAICS did not resolve, the
     business is not operating/early-stage, or the client's own line
     list is empty. THIN => no GPT call, no ask, zero spend. Silence is
     free; the generic checklist is the disease.
  2. ONE forced-tool, seeded GPT call per draft. Its schema returns
     candidates[] of {label, commonality in most|many|some} - LABELS
     ONLY. It has no channel for a number, a price, a volume or a
     sentence, so it cannot fabricate revenue.
  3. THE VALIDATOR IS THE FENCE, not the prompt: drop commonality=some;
     drop labels that are a paraphrase of a line the client already
     captured or a stream the client already described (the DISCOVERY
     dedup, F1 below - the ack-contradiction class in question form);
     drop labels carrying addition verbs (add/expand/consider/start/
     launch/new) so the upsell shape is unrepresentable. NO COUNT CAP ON
     THE BAND (Nick's correction): the band IS the gate; how many streams
     SURVIVE is a judgment, never a constant.
     F1 (Nick, 2026-08-15, Cormorant): dedup requires a DISTINGUISHING
     match. One shared token that is the business-type / NAICS-title
     category noun ('coffee' for a coffee roaster, 'dental', 'landscaping')
     is NOT a duplicate - every adjacent stream of a category-noun-heavy
     type carries that noun. A candidate is deduped only when it shares a
     NON-category token with a captured line, or >=2 tokens with one, or
     when its distinguishing tokens are what the client already described
     ('wholesale ... online' in the confirmed description => the primary
     and the mentioned stream stay deduped). This lives HERE, in
     discovery; the caller's line resolver (corrections rely on it) is
     untouched.
     F2 (Nick, 2026-08-15): the number lint stops fabricated FINANCIAL
     figures ($, per week, 40 units). A numeric SIZE qualifier ('12 oz
     retail coffee bags', '5 lb') is a descriptor, not a revenue number:
     it is STRIPPED from the label ('retail coffee bags'), never a reason
     to drop the candidate.
  3b. F3 PROPOSAL CAP (Nick, 2026-08-15): a UX / cognitive-load limit on
     the QUESTION, not a business heuristic - a client cannot answer a
     laundry-list ask in one breath. The band-gate surfaces however many
     genuinely-common streams it finds (all stored on the latch as
     `survivors`); the ASK proposes AT MOST 4 - all `most` first, then
     `many` - so the four asked about are the four most likely to apply,
     never an arbitrary four. 4 or fewer survive => all proposed, no
     padding. Still ONE ask, one turn. The cap is on the PROPOSAL ONLY:
     what the client volunteers through the normal flow is never blocked.
  4. The ask is ONE deterministic template constant, existence-framed;
     GPT never composes it. Only the proposed labels are interpolated.
  5. The client is the authority: nothing enters the model until the
     client says yes; unclear is NOT a yes (ruled); no is never re-asked.
  6. Inputs are exactly: business type, NAICS + title, stage, geography,
     the client's own lines and description. NO cohort/CBP data - it
     carries nothing about streams and would be false grounding.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

STREAM_DISCOVERY_VERSION = 1
STREAM_DISCOVERY_ORIGIN = "discovery_confirmed"

# The band: only genuinely common streams survive. "some" is dropped by the
# validator, whatever the judge argued. There is deliberately NO cap on how
# many survivors the band surfaces - the band is the gate. The ASK proposes
# at most STREAM_DISCOVERY_PROPOSAL_CAP of them (F3: a limit on the
# question's size, most-first, never on what the client may volunteer).
COMMONALITY_ENUM = ("most", "many", "some")
COMMONALITY_SURVIVES = ("most", "many")
STREAM_DISCOVERY_PROPOSAL_CAP = 4

# F2: numeric SIZE qualifiers are descriptors, not revenue numbers - they
# are stripped from a label, never a reason to drop it. Anything numeric
# that is NOT a size (money, rates, volumes, counts) still fails the lint.
_SIZE_UNITS = (
  "oz|ounce|ounces|fl oz|lb|lbs|pound|pounds|kg|kgs|kilo|kilos|kilogram|kilograms|"
  "g|gram|grams|mg|ml|l|liter|liters|litre|litres|gal|gallon|gallons|qt|quart|quarts|"
  "pt|pint|pints|cup|cups|inch|inches|in|ft|foot|feet|yd|yard|yards|cm|mm|m|meter|"
  "meters|metre|metres|sq ft|sqft|square foot|square feet|ct|count|pk|pack|packs|"
  "piece|pieces|pc|pcs"
)
_SIZE_QUALIFIER_RE = re.compile(
  r"(?<![\w$])\d+(?:[.,/]\d+)?\s*-?\s*(?:" + _SIZE_UNITS + r")\b\.?",
  re.IGNORECASE,
)

# Addition-verb lint: a label carrying any of these is the upsell shape and
# is dropped before it can reach the template.
ADDITION_VERBS = ("add", "expand", "consider", "start", "launch", "new")

# Stages the discovery question is meaningful for. A pre-revenue business
# has no "today" to ask about (the question drifts to "will you also" =
# upsell), so it is THIN by rule.
DISCOVERY_STAGES = ("operating", "early-stage")

# THE ASK - one constant, existence-framed. GPT never writes this sentence.
# F4 (Nick, 2026-08-15): the client is told WHY they are asked - a yes ADDS
# A REVENUE LINE to their plan - in one clause, so they answer knowingly;
# the template verb ("also offer") makes the noun-phrase labels read
# naturally (closes the label-grammar WATCH item).
STREAM_DISCOVERY_ASK_PREFIX = "Before we wrap up operations: a lot of "
STREAM_DISCOVERY_ASK_TEMPLATE = (
  STREAM_DISCOVERY_ASK_PREFIX
  + "{business_type_plural} also offer {labels} - is any of that part of your "
  "business today? (If so I'll include it as a revenue line.) If not, just say "
  "so and we'll move on."
)

# THE ONE CLARIFY (F4): when the reader cannot tell what the client meant for
# a stream, it asks ONCE - one closed question, same constant shape, only the
# still-open labels interpolate. The clarify answer is read the same way;
# still-unclear after it => not confirmed, never asked again.
STREAM_DISCOVERY_CLARIFY_PREFIX = "Just so I record it right: "
STREAM_DISCOVERY_CLARIFY_TEMPLATE = (
  STREAM_DISCOVERY_CLARIFY_PREFIX
  + "is {labels} part of your business today? A yes means I'll include it as a "
  "revenue line in your plan; if not, just say no and we'll move on."
)

# Words the emitted ask must never contain (mini's forbidden-phrase grep).
FORBIDDEN_ASK_PHRASES = ("consider", "add", "expand", "could you also", "would you")


# ---------------------------------------------------------------------------
# 1. Evidence level - PYTHON decides; thin => no call, no ask.
# ---------------------------------------------------------------------------

def _client_lines(ops_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  for lob in (ops_json or {}).get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    for p in lob.get("products") or []:
      if isinstance(p, dict) and str(p.get("product_name") or "").strip():
        out.append({
          "lob_name": str(lob.get("lob_name") or "").strip(),
          "product_name": str(p.get("product_name") or "").strip(),
          "unit_name": str(p.get("unit_name") or "").strip(),
        })
  return out


def stream_discovery_evidence_level(
  ops_json: Optional[Dict[str, Any]],
  *,
  stage_hint: Optional[str] = None,
) -> Dict[str, Any]:
  """PYTHON-side evidence classification. RICH only when every keyed fact
  the judge needs is actually held: a client-selected business_type, a
  resolved 6-digit NAICS, an operating/early-stage business, and at least
  one client-stated line. Any gap => THIN => silence."""
  ops = ops_json if isinstance(ops_json, dict) else {}
  reasons: List[str] = []
  if not str(ops.get("business_type") or "").strip():
    reasons.append("no_business_type")
  naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit())
  if len(naics) != 6:
    reasons.append("naics_unresolved")
  stage = str(ops.get("business_stage") or stage_hint or "").strip().lower()
  if not stage:
    reasons.append("stage_unknown")
  elif stage not in DISCOVERY_STAGES:
    reasons.append(f"stage_not_discoverable:{stage}")
  if not _client_lines(ops):
    reasons.append("no_client_lines")
  return {"level": "thin" if reasons else "rich", "reasons": reasons}


# ---------------------------------------------------------------------------
# 2. The ONE judge call - labels only.
# ---------------------------------------------------------------------------

_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_stream_discovery_candidates",
    "description": (
      "Submit the revenue streams that businesses of THIS type commonly "
      "have TODAY which the client has not mentioned. Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "label": {
                "type": "string",
                "description": (
                  "A short, plain noun phrase a business owner would use "
                  "for the stream (e.g. 'delivery service', 'repair work'). "
                  "Never a sentence, never a number, never a suggestion."
                ),
              },
              "commonality": {
                "type": "string",
                "enum": list(COMMONALITY_ENUM),
                "description": (
                  "'most' = the majority of businesses of this type have "
                  "this stream; 'many' = a substantial minority; 'some' = "
                  "occasionally. Rate honestly for THIS type, size and "
                  "geography - not for the industry at large."
                ),
              },
            },
            "required": ["label", "commonality"],
          },
        },
        "basis": {
          "type": "string",
          "description": "One or two sentences on what about this business type drives the list.",
        },
      },
      "required": ["candidates", "basis"],
    },
  },
}

_SYSTEM_PROMPT = (
  "You are judging one narrow category question for a business-planning "
  "interview: which REVENUE STREAMS do businesses of THIS type usually "
  "already have that this client has NOT mentioned? You will be shown the "
  "client-selected business type, its NAICS code and title, the business "
  "stage and geography, and - most importantly - the client's OWN list of "
  "lines and their own description of the business.\n"
  "RULES:\n"
  "1. EXISTENCE, NOT ADDITION. You are naming streams that a business like "
  "this typically has TODAY, so the interviewer can ask whether they exist. "
  "You are NOT suggesting what the client could add, expand, start or "
  "launch. Never phrase a label as an idea or a suggestion.\n"
  "2. LABELS ONLY. Each candidate is a short plain noun phrase an owner "
  "would use. No numbers, no prices, no volumes, no sentences.\n"
  "3. DO NOT REPEAT the client's own lines or a paraphrase of them. If the "
  "client already listed it (under any name), leave it out.\n"
  "4. RATE COMMONALITY HONESTLY for this specific type, size and place: "
  "'most' = the majority of such businesses have it; 'many' = a "
  "substantial minority; 'some' = occasionally. Do not inflate to be "
  "helpful - only genuinely common streams will be asked about, and a "
  "generic checklist wastes the client's time.\n"
  "5. If nothing genuinely common is missing, return an empty list.\n"
  "Call submit_stream_discovery_candidates exactly once."
)


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


def build_discovery_inputs(
  ops_json: Optional[Dict[str, Any]],
  *,
  naics_title: Optional[str],
  stage_hint: Optional[str] = None,
) -> Dict[str, Any]:
  """EXACTLY the spec's inputs: type, NAICS + title, stage, geography, the
  client's own lines and description. Nothing else is passed."""
  ops = ops_json if isinstance(ops_json, dict) else {}
  return {
    "business_type": str(ops.get("business_type") or "").strip(),
    "business_naics_6": str(ops.get("business_naics_6") or "").strip(),
    "naics_title": str(naics_title or "").strip(),
    "business_stage": str(ops.get("business_stage") or stage_hint or "").strip().lower(),
    "geography": {
      "geographic_scope": ops.get("geographic_scope"),
      "geographic_coverage": ops.get("geographic_coverage"),
      "countries": ops.get("countries"),
    },
    "client_lines": _client_lines(ops),
    "business_description_summary": str(ops.get("business_description_summary") or "").strip(),
  }


def gpt_author_stream_candidates_once(
  *,
  inputs: Dict[str, Any],
  model: Optional[str] = None,
  seed: int = 1741,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """ONE category-judgment call; returns {ok, judgment, error}. RAW -
  callers must pass the result through validate_stream_candidates."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "judgment": None, "error": "openai_api_key_unset"}
  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries
  user = (
    "THE BUSINESS (client-selected type, resolved NAICS, stage, geography):\n"
    + json.dumps({k: inputs.get(k) for k in (
        "business_type", "business_naics_6", "naics_title", "business_stage", "geography",
      )}, ensure_ascii=False, default=str)
    + "\n\nTHE CLIENT'S OWN LINES (already captured - never repeat these):\n"
    + json.dumps(inputs.get("client_lines") or [], ensure_ascii=False, default=str)
    + "\n\nTHE CLIENT'S OWN DESCRIPTION:\n"
    + str(inputs.get("business_description_summary") or "")
  )
  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function",
                    "function": {"name": "submit_stream_discovery_candidates"}},
    "seed": int(seed),
  }
  headers = {"Authorization": f"Bearer {api_key}",
             "Content-Type": "application/json"}
  try:
    resp = http_fn(
      url=_OPENAI_URL, headers=headers, payload=payload,
      timeout_seconds=timeout_seconds,
      retryable_status=(429, 500, 502, 503, 504), max_attempts=3,
    )
  except Exception as exc:
    return {"ok": False, "judgment": None,
            "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}
  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "judgment": None, "error": f"http_status_{status}"}
  try:
    body = resp.json()
    message = (body.get("choices") or [{}])[0].get("message") or {}
    fn = ((message.get("tool_calls") or [{}])[0] or {}).get("function") or {}
    args_raw = fn.get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
  except Exception as exc:
    return {"ok": False, "judgment": None,
            "error": f"tool_call_parse_failed:{type(exc).__name__}"}
  if not isinstance(parsed, dict):
    return {"ok": False, "judgment": None, "error": "no_judgment_in_tool_call"}
  return {"ok": True, "judgment": parsed, "error": None}


# ---------------------------------------------------------------------------
# 3. The validator - the fence. NO COUNT CAP.
# ---------------------------------------------------------------------------

def _stem(tok: str) -> str:
  # Crude, deterministic: deliveries->delivery, services->service, jobs->job.
  if tok.endswith("ies") and len(tok) > 4:
    return tok[:-3] + "y"
  if tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
    return tok[:-1]
  return tok


def _label_tokens(text: str) -> List[str]:
  return [_stem(t) for t in re.findall(r"[a-z]+", str(text or "").lower())]


def label_carries_addition_verb(label: str) -> bool:
  toks = set(_label_tokens(label))
  for verb in ADDITION_VERBS:
    # 'new' as a whole word; the others as stems (adds/adding/expanding...).
    if verb == "new":
      if "new" in toks:
        return True
    elif any(t == verb or (t.startswith(verb) and len(t) <= len(verb) + 3) for t in toks):
      return True
  return False


def _clean_label(raw: Any) -> str:
  s = " ".join(str(raw or "").strip().split())
  s = s.strip(" .;:!?\"'")
  return s


def strip_size_qualifiers(label: str) -> str:
  """F2: remove numeric SIZE descriptors ('12 oz', '5 lb', '500ml',
  '2-pack') from a label. Returns the cleaned label; anything numeric that
  is NOT a size is left in place for the number lint to catch."""
  out = _SIZE_QUALIFIER_RE.sub(" ", str(label or ""))
  out = re.sub(r"\s+", " ", out).strip(" -,/")
  return _clean_label(out)


def _tokens4(text: Any) -> set:
  return {t for t in _label_tokens(text) if len(t) >= 4}


def _tok_hit(a: str, b: str) -> bool:
  # The caller's resolver rule, unchanged: stem-prefix either way.
  return a == b or a.startswith(b) or b.startswith(a)


def _shared(label_toks: set, other_toks: set) -> set:
  return {lt for lt in label_toks if any(_tok_hit(lt, ot) for ot in other_toks)}


def discovery_category_tokens(ops_json: Optional[Dict[str, Any]], naics_title: str = "") -> set:
  """F1: the CATEGORY nouns of this business - the stems of the client-
  selected business_type and the NAICS title, plus the token of each LOB
  name that is one of them ('coffee' in 'Roasted coffee'). Sharing ONE of
  these with a captured line is not a duplicate; every adjacent stream of
  a category-noun-heavy type carries it."""
  ops = ops_json if isinstance(ops_json, dict) else {}
  cat = _tokens4(ops.get("business_type")) | _tokens4(naics_title)
  for lob in ops.get("lob_models") or []:
    if isinstance(lob, dict):
      cat |= _shared(_tokens4(lob.get("lob_name")), cat)
  return cat


def discovery_dedup_reason(
  label: str,
  ops_json: Optional[Dict[str, Any]],
  *,
  category_tokens: set,
) -> Optional[str]:
  """F1 - the DISCOVERY dedup (the resolver used for corrections is not
  touched). Returns the drop reason or None (survives).

  matches_existing_line: the label shares a DISTINGUISHING token (one that
    is not a category noun) with a captured row's product/unit/LOB name,
    or >=2 tokens with one row.
  mentioned_by_client: the label's distinguishing tokens are what the
    client already described (the client-confirmed business description
    and the rows' unit descriptions): all of them when there are one or
    two, at least two and a majority otherwise. The primary line and a
    stream the client named in passing ('wholesale ... online') stay
    deduped without the category noun doing the work."""
  ops = ops_json if isinstance(ops_json, dict) else {}
  ltoks = _tokens4(label)
  if not ltoks:
    return None
  distinguishing = {t for t in ltoks if not any(_tok_hit(t, c) for c in category_tokens)}
  desc_toks: set = _tokens4(ops.get("business_description_summary"))
  for lob in ops.get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    for p in lob.get("products") or []:
      if not isinstance(p, dict):
        continue
      row_toks = _tokens4(p.get("product_name")) | _tokens4(p.get("unit_name")) | _tokens4(lob.get("lob_name"))
      shared = _shared(ltoks, row_toks)
      if shared & distinguishing or len(shared) >= 2:
        return "matches_existing_line"
      desc_toks |= _tokens4(p.get("unit_description"))
  if distinguishing:
    hits = _shared(distinguishing, desc_toks)
    n, k = len(hits), len(distinguishing)
    if (k <= 2 and n == k) or (k > 2 and n >= 2 and n * 2 > k):
      return "mentioned_by_client"
  return None


def propose_from_survivors(survivors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  """F3: the proposed slice - ALL `most` first (in judge order), then
  `many`, at most STREAM_DISCOVERY_PROPOSAL_CAP. <= cap => all, no padding."""
  most = [c for c in survivors if c.get("commonality") == "most"]
  many = [c for c in survivors if c.get("commonality") != "most"]
  return (most + many)[:STREAM_DISCOVERY_PROPOSAL_CAP]


def validate_stream_candidates(
  *,
  judgment: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  naics_title: str = "",
) -> Dict[str, Any]:
  """Rail the raw judgment into {candidates, survivors, dropped}. Every
  rule is mechanical: enum band (some dropped), F2 size-strip then the
  number lint, addition-verb lint, empty/duplicate/over-long labels, F1
  discovery dedup against the client's own lines and description.
  `survivors` = everything the band-gate let through (no cap);
  `candidates` = the F3 proposed slice (most-first, at most
  STREAM_DISCOVERY_PROPOSAL_CAP) - the labels the ask names."""
  j = judgment if isinstance(judgment, dict) else {}
  raw = j.get("candidates")
  survivors: List[Dict[str, Any]] = []
  dropped: List[Dict[str, Any]] = []
  seen: set = set()
  if not isinstance(raw, list):
    return {"candidates": [], "survivors": survivors, "dropped": dropped}
  category_tokens = discovery_category_tokens(ops_json, naics_title)
  for item in raw:
    if not isinstance(item, dict):
      continue
    judge_label = _clean_label(item.get("label"))
    label = strip_size_qualifiers(judge_label)
    commonality = str(item.get("commonality") or "").strip().lower()
    if not label:
      if judge_label:
        dropped.append({"label": judge_label, "reason": "label_not_a_short_phrase"})
      continue
    if len(label) > 60 or len(_label_tokens(label)) > 6:
      dropped.append({"label": label, "reason": "label_not_a_short_phrase"})
      continue
    if re.search(r"\d", label):
      dropped.append({"label": label, "reason": "label_carries_number"})
      continue
    if commonality not in COMMONALITY_ENUM:
      dropped.append({"label": label, "reason": "commonality_invalid"})
      continue
    if commonality not in COMMONALITY_SURVIVES:
      dropped.append({"label": label, "reason": "commonality_some"})
      continue
    if label_carries_addition_verb(label):
      dropped.append({"label": label, "reason": "addition_verb"})
      continue
    key = " ".join(_label_tokens(label))
    if key in seen:
      dropped.append({"label": label, "reason": "duplicate_label"})
      continue
    why = discovery_dedup_reason(label, ops_json, category_tokens=category_tokens)
    if why:
      dropped.append({"label": label, "reason": why})
      continue
    seen.add(key)
    cand: Dict[str, Any] = {"label": label, "commonality": commonality, "answer": None}
    if label != judge_label:
      cand["judge_label"] = judge_label
    survivors.append(cand)
  proposed = propose_from_survivors(survivors)
  return {"candidates": proposed, "survivors": survivors, "dropped": dropped}


# ---------------------------------------------------------------------------
# 4. The ask - one template constant.
# ---------------------------------------------------------------------------

def pluralize_business_type(business_type: str) -> str:
  bt = " ".join(str(business_type or "").strip().lower().split())
  if not bt:
    return "businesses like yours"
  words = bt.split(" ")
  last = words[-1]
  if re.search(r"(s|x|z|ch|sh)$", last):
    last = last + "es"
  elif re.search(r"[^aeiou]y$", last):
    last = last[:-1] + "ies"
  else:
    last = last + "s"
  words[-1] = last
  return " ".join(words)


def join_labels(labels: List[str]) -> str:
  labs = [str(x).strip() for x in labels if str(x or "").strip()]
  if not labs:
    return ""
  if len(labs) == 1:
    return labs[0]
  return ", ".join(labs[:-1]) + " or " + labs[-1]


def compose_stream_discovery_ask(business_type: str, labels: List[str]) -> str:
  return STREAM_DISCOVERY_ASK_TEMPLATE.format(
    business_type_plural=pluralize_business_type(business_type),
    labels=join_labels(labels),
  )


def compose_stream_discovery_clarify(labels: List[str]) -> str:
  labs = [str(x).strip() for x in labels if str(x or "").strip()]
  phrase = join_labels(labs) if len(labs) <= 1 else "any of " + join_labels(labs)
  return STREAM_DISCOVERY_CLARIFY_TEMPLATE.format(labels=phrase)


def is_stream_discovery_ask(text: str) -> bool:
  """True when the assistant text is the discovery window - the ask itself
  or its ONE clarify (the reply to either is read as a discovery answer)."""
  low = str(text or "").lower()
  return (
    STREAM_DISCOVERY_ASK_PREFIX.lower() in low
    or STREAM_DISCOVERY_CLARIFY_PREFIX.lower() in low
  )


# ---------------------------------------------------------------------------
# 5. Reading the answer - INTENT, per candidate, through the app's existing
#    intent door. F4 (Nick, 2026-08-15): the token/keyword scoring that lived
#    here read 'No, none of those. We just do the five pound wholesale bags.'
#    as a YES for 'wholesale subscription contracts' (a word inside a decline
#    is not a yes) - string-matching heuristics are not how this app reads a
#    client. The reply is now routed, per proposed stream, through the SAME
#    ACCEPT/REJECT/CLARIFY reader the ops turn already uses for a reply to a
#    proposal (intake_consult._classify_restatement_response) - the caller
#    hands that door in; this module holds NO keyword logic. ACCEPT => yes,
#    REJECT => no, CLARIFY (or a door failure) => unclear => the caller asks
#    ONE clarify; still unclear => not confirmed, never re-asked.
# ---------------------------------------------------------------------------

def stream_discovery_intent_frame(ask_text: str, labels: List[str], label: str) -> str:
  """The proposition the intent door checks the reply against, for ONE
  stream. Deterministic text: the ask, the streams it named, the stream
  under judgment, and the reading rules (a yes adds a revenue line, so a
  confirmation must be real; a word inside a decline is not a yes; a hedge
  or a bare yes to a several-stream question is CLARIFY; each stream is
  confirmed on its own words only)."""
  labs = [str(x).strip() for x in labels if str(x or "").strip()]
  return (
    "CONTEXT. The app asked the client ONE question about their business as it "
    f"exists TODAY, naming {len(labs)} possible revenue stream(s):\n\"{str(ask_text or '').strip()}\"\n"
    f"Streams named in the question: {', '.join(labs)}.\n"
    "A stream the client confirms becomes a revenue line in their business plan, so a "
    "confirmation must be real: this is NOT a restatement the client is agreeing with in "
    "general - it is a yes/no about ONE named stream.\n"
    f"RESTATEMENT TO CHECK: \"{str(label or '').strip()}\" is part of the client's business today.\n"
    "Rules for THIS ONE stream:\n"
    "- ACCEPT only if the reply clearly confirms THIS stream: by name, by an unmistakable "
    "reference to it, by confirming all of the streams (\"all of those\", \"yes to everything\"), "
    "or - when the question named only one stream - by a plain yes.\n"
    "- REJECT if the reply declines it: explicitly, by declining all of them (\"no\", \"none of "
    "those\"), by naming only OTHER streams from the list as theirs, or by describing what they "
    "do instead. A word from this stream's name appearing inside a decline is NOT a yes.\n"
    "- CLARIFY if you cannot tell for this stream: a hedge (\"sort of\", \"sometimes\", \"maybe\", "
    "\"kind of\"), a bare \"yes\"/\"yeah\" to a question that named several streams without saying "
    "WHICH, a question back, or an off-topic reply. Nuance or a caveat is NOT agreement here - "
    "when unsure, CLARIFY, never ACCEPT.\n"
    "- Each stream stands on its own words. Being related to, similar to, or commonly bundled "
    "with a stream the reply DID confirm is NOT confirmation of THIS one - if the reply confirms "
    "other streams and does not name or unmistakably refer to this one, REJECT."
  )


_DOOR_TO_ANSWER = {"ACCEPT": "yes", "REJECT": "no", "CLARIFY": "unclear"}


def read_stream_discovery_answer(
  message: str,
  labels: List[str],
  *,
  classify: Callable[..., Optional[str]],
  ask_text: str,
) -> Dict[str, str]:
  """Per-candidate INTENT reading through the app's existing intent door.
  `classify(restatement=..., user_reply=...)` is the ACCEPT/REJECT/CLARIFY
  reader (production: intake_consult._classify_restatement_response); it is
  called once per proposed stream with the stream's frame. Returns
  {label: yes|no|unclear}. No keyword, phrase or token logic lives here:
  if the door cannot read the reply (CLARIFY, None, or an exception), the
  answer is 'unclear' and the caller asks - it never guesses."""
  labs = [str(x).strip() for x in labels if str(x or "").strip()]
  out: Dict[str, str] = {lab: "unclear" for lab in labs}
  text = str(message or "").strip()
  if not labs or not text:
    return out
  for lab in labs:
    try:
      verdict = classify(
        restatement=stream_discovery_intent_frame(ask_text, labs, lab),
        user_reply=text,
      )
    except Exception:
      verdict = None
    out[lab] = _DOOR_TO_ANSWER.get(str(verdict or "").strip().upper(), "unclear")
  return out


def _mention_hits(candidate_tokens: List[str], clause_tokens: set) -> int:
  n = 0
  for ct in candidate_tokens:
    if any(ct == mt or ct.startswith(mt) or mt.startswith(ct) for mt in clause_tokens):
      n += 1
  return n


# ---------------------------------------------------------------------------
# 6. Landing a yes: PYTHON appends the row (receipt law: words == state).
# ---------------------------------------------------------------------------

def stem_match_lob_index(ops_json: Dict[str, Any], label: str) -> Optional[int]:
  """The LOB a confirmed stream belongs under: the unique LOB whose name
  shares a stem with the label; None (=> new LOB named for the label)
  when none or several match."""
  ltoks = [t for t in _label_tokens(label) if len(t) >= 4]
  if not ltoks:
    return None
  hits: List[int] = []
  for li, lob in enumerate((ops_json or {}).get("lob_models") or []):
    if not isinstance(lob, dict):
      continue
    ntoks = {t for t in _label_tokens(lob.get("lob_name")) if len(t) >= 4}
    if _mention_hits(ltoks, ntoks) > 0:
      hits.append(li)
  return hits[0] if len(hits) == 1 else None


def new_discovered_row(label: str) -> Dict[str, Any]:
  return {
    "product_name": str(label).strip(),
    "unit_name": None,
    "unit_description": None,
    "unit_cadence": None,
    "units_per_week_capacity": None,
    "units_per_period_capacity": None,
    "operating_periods_per_year": None,
    "utilization_rate": None,
    "unit_price": None,
    "cogs_percent_of_line_revenue": None,
    "origin": STREAM_DISCOVERY_ORIGIN,
  }


def _row_named(p: Dict[str, Any], label: str) -> bool:
  return " ".join(_label_tokens(p.get("product_name"))) == " ".join(_label_tokens(label))


def append_confirmed_stream_rows(
  ops_json: Dict[str, Any], labels: List[str],
) -> Tuple[Dict[str, Any], List[str]]:
  """Append one null-driver product row per confirmed label (idempotent:
  a row already named for the label is stamped, not duplicated). Returns
  (ops_json, receipt_lines) - the receipt says exactly what was written."""
  ops = ops_json if isinstance(ops_json, dict) else {}
  lobs = ops.get("lob_models")
  if not isinstance(lobs, list):
    lobs = []
    ops["lob_models"] = lobs
  receipts: List[str] = []
  for label in labels:
    label = str(label or "").strip()
    if not label:
      continue
    found = False
    for lob in lobs:
      if not isinstance(lob, dict):
        continue
      for p in lob.get("products") or []:
        if isinstance(p, dict) and _row_named(p, label):
          p.setdefault("origin", STREAM_DISCOVERY_ORIGIN)
          if not p.get("origin"):
            p["origin"] = STREAM_DISCOVERY_ORIGIN
          found = True
    if found:
      receipts.append(f"Noted - {label} is its own line; a few quick numbers for it next.")
      continue
    li = stem_match_lob_index(ops, label)
    if li is None:
      lobs.append({"lob_name": label, "products": [new_discovered_row(label)]})
      receipts.append(f"Noted - {label} is its own line; a few quick numbers for it next.")
    else:
      prods = lobs[li].get("products")
      if not isinstance(prods, list):
        prods = []
        lobs[li]["products"] = prods
      prods.append(new_discovered_row(label))
      lob_name = str(lobs[li].get("lob_name") or "").strip() or "that line of business"
      receipts.append(
        f"Noted - {label} is its own line under {lob_name}; a few quick numbers for it next."
      )
  return ops, receipts


# ---------------------------------------------------------------------------
# 7. Carry-forward: the latch and the origin stamp survive every wholesale
#    lob_models replacement (model patch, finalize).
# ---------------------------------------------------------------------------

def carry_stream_discovery(
  before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """Idempotent. (1) The stream_discovery latch written on `before` is
  re-attached to `after` if the replacement lost it. (2) Every confirmed
  label has EXACTLY ONE product row carrying origin=discovery_confirmed:
  the row named for it is re-stamped; a same-named duplicate minted by the
  model is removed; a row the model dropped is re-appended (from the
  before-row if it exists, else null-driver fresh)."""
  if not isinstance(after, dict):
    return after
  latch = (before or {}).get("stream_discovery") if isinstance(before, dict) else None
  if isinstance(latch, dict) and not isinstance(after.get("stream_discovery"), dict):
    after["stream_discovery"] = json.loads(json.dumps(latch))
  latch = after.get("stream_discovery")
  confirmed = [
    str(c.get("label") or "").strip()
    for c in ((latch.get("candidates") or []) if isinstance(latch, dict) and latch.get("asked") else [])
    if isinstance(c, dict) and str(c.get("answer") or "") == "yes" and str(c.get("label") or "").strip()
  ]
  # PROVENANCE IS OURS, NEVER THE MODEL'S: the only defined origin value is
  # discovery_confirmed and only a latched YES may carry it. Anything else
  # the strict-schema model wrote into origin (live: it invented values on
  # ordinary rows) is scrubbed to null. The stamp means one thing.
  for lob in after.get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    for p in lob.get("products") or []:
      if not isinstance(p, dict) or "origin" not in p:
        continue
      if p.get("origin") is None:
        continue
      if p.get("origin") != STREAM_DISCOVERY_ORIGIN or not any(_row_named(p, c) for c in confirmed):
        p["origin"] = None
  if not confirmed:
    return after
  lobs = after.get("lob_models")
  if not isinstance(lobs, list):
    lobs = []
    after["lob_models"] = lobs
  for label in confirmed:
    matches: List[Tuple[int, int]] = []
    for li, lob in enumerate(lobs):
      if not isinstance(lob, dict):
        continue
      for pi, p in enumerate(lob.get("products") or []):
        if isinstance(p, dict) and _row_named(p, label):
          matches.append((li, pi))
    if matches:
      # Keep the row that carries the most client-given values (a
      # duplicate the model minted is the null one); ties keep the first.
      def _filled(m: Tuple[int, int]) -> int:
        row = lobs[m[0]]["products"][m[1]]
        return sum(
          1 for k in ("unit_name", "unit_cadence", "units_per_week_capacity",
                      "units_per_period_capacity", "utilization_rate", "unit_price")
          if row.get(k) not in (None, "", 0)
        )
      keep_li, keep_pi = max(matches, key=lambda m: (_filled(m), -matches.index(m)))
      lobs[keep_li]["products"][keep_pi]["origin"] = STREAM_DISCOVERY_ORIGIN
      for li, pi in sorted([m for m in matches if m != (keep_li, keep_pi)], reverse=True):
        try:
          del lobs[li]["products"][pi]
        except Exception:
          pass
      continue
    # Dropped by the replacement: restore the before-row (drivers the client
    # may already have given) or a fresh null row.
    restored: Optional[Dict[str, Any]] = None
    for lob in ((before or {}).get("lob_models") or []) if isinstance(before, dict) else []:
      if not isinstance(lob, dict):
        continue
      for p in lob.get("products") or []:
        if isinstance(p, dict) and _row_named(p, label):
          restored = json.loads(json.dumps(p))
          restored["origin"] = STREAM_DISCOVERY_ORIGIN
          break
      if restored is not None:
        break
    row = restored if restored is not None else new_discovered_row(label)
    li = stem_match_lob_index(after, label)
    if li is None:
      lobs.append({"lob_name": label, "products": [row]})
    else:
      prods = lobs[li].get("products")
      if not isinstance(prods, list):
        prods = []
        lobs[li]["products"] = prods
      prods.append(row)
  # Empty LOBs left by duplicate removal are dropped.
  after["lob_models"] = [
    lob for lob in lobs
    if not (isinstance(lob, dict) and isinstance(lob.get("products"), list) and not lob["products"])
  ]
  return after


def stream_discovery_pending(ops_json: Optional[Dict[str, Any]]) -> bool:
  latch = (ops_json or {}).get("stream_discovery") if isinstance(ops_json, dict) else None
  if not isinstance(latch, dict) or not latch.get("asked"):
    return False
  return any(
    isinstance(c, dict) and c.get("answer") is None
    for c in (latch.get("candidates") or [])
  )
