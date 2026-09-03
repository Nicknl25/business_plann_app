"""THE SECTION AUTHOR (2026-09-01) - the one writing-phase module that calls GPT.

rules.py states the rules, checks.py holds them, facts/ supplies the material,
payload.py builds the strings. This module is the door those meet at: it sends
one section's prompt, receives class-tagged sentences with {{fact:key}} tokens,
runs the per-section check battery, and renders the tokens through the one
formatter. It writes no rules of its own - guidance here is authoring craft
(what the section covers, in what order), not enforcement.

THE REPAIR ROUND: a section whose checks fail is sent back ONCE with the
failures named. A second failure is returned honestly - the runner reports it,
nothing retries silently forever, and per the standing law an unrunnable check
is a failed section, never a skipped one.

Calls ride post_openai_with_retries, so the GPT response lock and call vitals
apply exactly as they do on the intake side.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from . import checks as CK
from . import payload as PL
from . import rules as R
from .facts.assembler import SectionBrief
from .facts.catalog import FactCatalog

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 300.0
_SEED = 2026

SUBMIT_TOOL = {
  "type": "function",
  "function": {
    "name": "submit_section",
    "description": "Submit the finished section as classified sentences.",
    "parameters": {
      "type": "object",
      "properties": {
        "sentences": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "text": {"type": "string"},
              "class": {"type": "string", "enum": list(R.SENTENCE_CLASSES)},
              "paragraph": {"type": "integer"},
            },
            "required": ["text", "class", "paragraph"],
          },
        },
        "notes": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              # digits only - the [^n] marker grammar is numeric, and an id
              # like "N1" can never be referenced (found live 2026-09-01)
              "id": {"type": "string", "pattern": "^[0-9]+$"},
              "kind": {"type": "string", "enum": list(R.NOTE_KINDS)},
              "text": {"type": "string"},
              "source_name": {"type": "string"},
              "source_vintage": {"type": "string"},
            },
            "required": ["id", "kind", "text"],
          },
        },
      },
      "required": ["sentences", "notes"],
    },
  },
}

_SYSTEM_PROMPT = (
  "You write one section of a client's business plan. The rules in the brief "
  "are binding; the ones that matter mechanically: tag every sentence "
  "GROUNDED, INFERRED or FRAMING; never type a digit - every figure is a "
  "{{fact:key}} token from the SECTION FACTS block, exactly as keyed - a key "
  "that is not in SECTION FACTS does not exist, never invent or vary one; third "
  "person by business name, never we/our/you; never say anything was "
  "unavailable; never mention models, systems or data pipelines. "
  "CLASSING RUBRIC: a sentence that restates what the client stated or what "
  "the record holds - the description, the advantage, coverage, the team, a "
  "referenced figure - is GROUNDED; grounded does not require a number. "
  "INFERRED is only for reasoning BEYOND the record, such as industry "
  "context. FRAMING is rare, contentless connective tissue - a closing "
  "synthesis that names the business, references facts or draws the record "
  "together is INFERRED, never FRAMING. Most sentences are GROUNDED. "
  "Say 'the business model' or 'the operating model', never bare 'the "
  "model'. "
  "Digit-bearing identifiers the client stated - a certification, a ZIP "
  "code - are FACTS where extracted (entity.stated_certifications, "
  "entity.coverage_zip): reference them as tokens like any other figure. "
  "Only when such an identifier is NOT among the facts, refer to it without "
  "the numeral. NAICS codes are digits: never type one - the industry scope "
  "is the fact industry.bds_scope_label, referenced as a token. Never place "
  "approximately, around, roughly or about before a fact token - rendered "
  "figures are exact ('in and near' for places, not 'around'). "
  "NAMING: name the business in full at first mention and again only where "
  "it genuinely helps; after that write normally - the company, the "
  "business, the firm, it. No one repeats a full legal name in every "
  "sentence. Keep the section visibly about THIS business through its "
  "specifics: named people, real places, fact tokens, the client's own "
  "detail. A sentence with no name, no back-reference, no person, no place "
  "and no token reads as anyone's - give it one. "
  "STYLE: avoid stock plan-writing constructions - 'enters the plan period "
  "with', 'Looking ahead', 'is driven primarily by', 'is built on', 'is "
  "built around'. Write the way a person describing this particular company "
  "would; the rhythm comes from the material, not from a template. Make "
  "each argument ONCE - a point established early is referenced later, "
  "never argued again. Do not end with a summary paragraph: sections do "
  "not need summaries; when the material is covered, stop. No intensifiers "
  "the record cannot back - 'exceptionally', 'unusually', 'rare' need a "
  "comparison we hold; where the intensity is the client's own claim, "
  "report it as their framing, never assert it as measured fact. A "
  "sentence that would be true of any competitor does not become about "
  "this business by naming its city - anchor claims in the client's "
  "specifics or cut them. "
  "When in doubt whether a "
  "client-stated claim is GROUNDED or INFERRED, it is GROUNDED. "
  "NOTES: most sentences carry NO note. Add one only where a reader would "
  "ask 'says who' - an industry statistic, a benchmark - never on the "
  "business's own identity or the client's own statements about themselves. "
  "The marker sits on the ONE sentence carrying the sourced claim, never on "
  "the sentences around it. "
  "A note only exists through its marker in a sentence: \"...are still "
  "operating five years later.[^1]\" paired with notes: [{\"id\": \"1\", "
  "\"kind\": \"BASIS\", \"text\": \"U.S. Census Bureau Business Dynamics "
  "Statistics, establishment survival by industry.\"}]. The text names the "
  "source plainly in one sentence - no lead-in labels. Every declared note "
  "must be marked in at least one sentence; an empty notes array is fine. "
  "Take each note's kind from the fact's own note_kind in the brief; never "
  "invent a SOURCE or a vintage. Keep "
  "sentences under 40 words - a closing synthesis especially: two short "
  "sentences beat one long one. Use correct articles before rendered values: "
  "'an LLC', never 'a LLC'. Submit via the submit_section tool only.")

# Authoring craft per section - what it covers and in what order. Craft, not
# rules: nothing here may contradict rules.py, and the checks do not read it.
SECTION_GUIDANCE: Dict[str, str] = {
  "the_business": (
    "Write The Business - the reader's first real look at the company. The "
    "section runs one to two pages: stop when it has said what it has to "
    "say - a section that ends early is better than one that fills the "
    "space. The reader wants to know what "
    "this company is, how long it has stood and what that means, where it "
    "stands today, and what it is actually built on.\n"
    "The section must cover the company's identity - name, legal form, when "
    "it was founded, where it sits and where it operates, in the client's "
    "own coverage. It must cover the tenure observation the brief carries, "
    "and the rate itself is the point: state the number with its horizon and "
    "draw the conclusion it earns - past year five, the business has already "
    "outlasted the cut that removes a large share of its cohort; give that "
    "argument the room it needs. It must cover the current position as "
    "stated: the trailing revenue, the team, and what the record shows the "
    "business holds today - never compared to a projection, because the "
    "Financial Plan owns that comparison. And it must cover what the "
    "business is built on: the advantage as the mechanism of THIS company, "
    "in the client's own framing where their words exist, without arguing "
    "against competitors - the Competitive Landscape owns versus-whom. "
    "Where the stated growth lever carries real content, say where the "
    "business is going in plain words; where it is absent, end at what "
    "it's built on.\n"
    "Every observation in the brief whose facts resolve must arrive on the "
    "page - none may be dropped as uninteresting. But what to lead with, "
    "how the pieces connect, and anything you reason out across the whole "
    "record that no observation names is your job.\n"
    "Never: mission statements, market sizes, competitor claims, projected "
    "figures, prices or unit economics (Products & Services owns those), "
    "how work is fulfilled day to day - lead times, scheduling, crew "
    "logistics (Operations owns those), anyone's years of experience "
    "(Management Team owns those), the client's stated milestones - an "
    "intake aspiration nothing models, never presented as the plan's "
    "objective - invented history, or references to figure or section "
    "numbers.")
}


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


def author_once(shared_block: str, section_block: str, guidance: str, *,
                model: Optional[str] = None, seed: int = _SEED,
                timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
                repair_feedback: str = "",
                _http: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
  """One authoring call. Returns {ok, payload, error}. RAW - callers run the
  check battery; nothing here decides a section passed."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "payload": None, "error": "openai_api_key_unset"}
  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import post_openai_with_retries
    http_fn = post_openai_with_retries
  user = PL.build_prompt(shared_block, section_block)
  user += "\n== HOW TO WRITE THIS SECTION ==\n" + guidance
  if repair_feedback:
    user += ("\n== YOUR PREVIOUS ATTEMPT FAILED THESE CHECKS - FIX AND RESUBMIT ==\n"
             + repair_feedback)
  body = {
    "model": _resolve_model(model),
    "messages": [{"role": "system", "content": _SYSTEM_PROMPT},
                 {"role": "user", "content": user}],
    "tools": [SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_section"}},
    "seed": int(seed),
  }
  headers = {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"}
  try:
    resp = http_fn(url=_OPENAI_URL, headers=headers, payload=body,
                   timeout_seconds=timeout_seconds,
                   retryable_status=(429, 500, 502, 503, 504), max_attempts=3)
  except Exception as exc:  # noqa: BLE001
    return {"ok": False, "payload": None,
            "error": "http_error:%s:%s" % (type(exc).__name__, str(exc)[:200])}
  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "payload": None, "error": "http_status_%d" % status}
  try:
    b = resp.json()
    msg = (b.get("choices") or [{}])[0].get("message") or {}
    fn = ((msg.get("tool_calls") or [{}])[0] or {}).get("function") or {}
    args = fn.get("arguments")
    parsed = json.loads(args) if isinstance(args, str) else (args or {})
  except Exception as exc:  # noqa: BLE001
    return {"ok": False, "payload": None,
            "error": "tool_call_parse_failed:%s" % type(exc).__name__}
  if not isinstance(parsed, dict) or not parsed.get("sentences"):
    return {"ok": False, "payload": None, "error": "no_sentences_in_tool_call"}
  parsed["section_key"] = None  # set by the caller with the true key
  return {"ok": True, "payload": parsed, "error": None}


def _drop_orphan_notes(payload: Dict[str, Any]) -> None:
  """A declared note nothing marks is a generation artifact the reader could
  never see - GPT persists in emitting endnote-style orphans even under
  repair feedback (observed twice on 2026-09-01). Dropping them is recorded
  ON the payload, never silent, and the reverse defect (a marker without a
  note) still fails R11 hard."""
  referenced: set = set()
  for s in payload.get("sentences") or []:
    referenced.update(CK._SUPERSCRIPT_MARKER.findall(str(s.get("text") or "")))
  notes = payload.get("notes") or []
  orphans = [n for n in notes if str(n.get("id")) not in referenced]
  if orphans:
    payload["notes"] = [n for n in notes if str(n.get("id")) in referenced]
    payload["dropped_orphan_notes"] = orphans


def run_section_checks(section_payload: Dict[str, Any], brief: SectionBrief,
                       draft: Dict[str, Any], *, extra_tokens=None) -> List[CK.CheckResult]:
  """The per-section battery for authored prose. Document-level checks (R08,
  R13, R19-R23) run at document assembly, not here."""
  toks = CK.client_tokens_for_draft(draft, extra=extra_tokens)
  return [
    CK.check_readability(section_payload),
    CK.check_no_absence_language(section_payload),
    CK.check_no_machinery(section_payload),
    CK.check_specificity(section_payload, client_tokens=toks),
    CK.check_fact_tokens_resolve(section_payload, brief_facts=brief.facts),
    CK.check_notes(section_payload, brief_facts=brief.facts),
    CK.check_sentence_classes(section_payload),
    CK.check_voice(section_payload,
                   business_name=str(draft.get("business_name") or "")),
    CK.check_number_style(section_payload, brief_facts=brief.facts),
    CK.check_no_computation(section_payload,
                            business_name=str(draft.get("business_name") or "")),
    CK.check_namespace_scope(section_payload),
    # prose quality, STRUCTURAL ONLY (Nick 2026-09-02): the closer's
    # fact-reference structure and the word band. Repeated arguments,
    # intensified comparisons, genericity and narrative bleed are DECLARED
    # review-caught - see the honest ledger in rules.py.
    CK.check_summary_closer(section_payload),
    CK.check_length_band(section_payload),
  ]


# the distinctive fact behind each tenure observation - pruned from the brief
# alongside the observation, or the writer quotes the wrong-age rate anyway
# (it did, live, 2026-09-02)
_TENURE_FACTS = {"S11": ("industry.first_year_exit_rate",),
                 "S61": ("industry.five_year_survival_rate",)}


def observation_floor_check(payload: Dict[str, Any], brief: SectionBrief,
                            exclude_sentence_ids=()) -> CK.CheckResult:
  """THE FLOOR (Nick 2026-09-02): the observations were built as the things a
  section must be able to say - a floor, never a ceiling. Every observation
  whose facts RESOLVE in this brief must arrive in the section's substance
  (at least one of its distinctive facts referenced somewhere, notes
  included); an unresolved observation is never demanded (rule 3). What to
  lead with, how to connect them, and what the writer reasons out across the
  whole record is its job - this gate controls coverage, not arrangement.
  Reported under R09 (holistic): author-side, like identity_match."""
  from .facts import sentences as S
  from .facts.assembler import IDENTITY_KEYS
  toks: set = set()
  for s in payload.get("sentences") or []:
    toks.update(CK.FACT_TOKEN.findall(str(s.get("text") or "")))
  for n in payload.get("notes") or []:
    toks.update(CK.FACT_TOKEN.findall(str(n.get("text") or "")))
  missing = []
  for sent in S.sentences_for_section(str(payload.get("section_key") or "")):
    if str(sent["id"]) in set(exclude_sentence_ids):
      continue
    if not all(k in brief.facts for k in sent["needs"]):
      continue
    required = sent.get("floor_required")
    if required:
      # e.g. the tenure RATE itself (Nick 2026-09-02): the number is the
      # point, and year-of-operation alone does not cover the observation
      absent = [k for k in required if k not in toks]
      if absent:
        missing.append("%s requires: %s" % (sent["id"], ", ".join(absent)))
      continue
    distinctive = [k for k in sent["needs"] if k not in IDENTITY_KEYS]
    if distinctive and not any(k in toks for k in distinctive):
      missing.append("%s needs one of: %s" % (sent["id"], ", ".join(distinctive[:4])))
  return CK.CheckResult(
    "R09", True, not missing,
    "writing_observation_floor_unmet" if missing else None,
    "a resolved observation never arrived in the section" if missing else "",
    missing)


def _tenure_exclusions(section_key: str, cat: FactCatalog) -> tuple:
  """The age-pick made STRUCTURAL (Nick's ruling, enforced 2026-09-01 after
  the writer used the first-year exit line on an 11th-year business despite
  explicit guidance): years 1-3 see only S11, year 5 on sees only S61, the
  fourth year sees neither. A writer that never sees the wrong line cannot
  use it."""
  if section_key != "the_business":
    return ()
  f = cat.get_quiet("entity.years_operating")
  if f is None:
    return ()
  try:
    years = int(f.value)
  except (TypeError, ValueError):
    return ()
  if years <= 3:
    return ("S61",)
  if years == 4:
    return ("S11", "S61")
  return ("S11",)


def author_section(draft: Dict[str, Any], cat: FactCatalog, brief: SectionBrief,
                   *, shared_block: Optional[str] = None,
                   model: Optional[str] = None,
                   _http: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
  """Author + verify with one repair round. Returns
  {ok, payload, results, attempts, error}; ok means every check ran and
  passed."""
  section_key = brief.section_key
  shared = shared_block if shared_block is not None else PL.build_shared_block(draft)
  ex_ids = _tenure_exclusions(section_key, cat)
  ex_facts = tuple(f for i in ex_ids for f in _TENURE_FACTS.get(i, ()))
  section_block = PL.build_section_block(
    brief, exclude_sentence_ids=ex_ids, exclude_fact_keys=ex_facts)
  guidance = SECTION_GUIDANCE.get(section_key, "Write the section from its brief.")
  feedback = ""
  last: Dict[str, Any] = {"ok": False, "payload": None, "error": "not_attempted"}
  # two repair rounds (2026-09-02): the structural battery legitimately
  # catches more, and a third attempt with named failures beats a
  # deterministic FAIL under the GPT lock
  for attempt in (1, 2, 3):
    got = author_once(shared, section_block, guidance, model=model,
                      seed=_SEED + attempt - 1, repair_feedback=feedback, _http=_http)
    if not got["ok"]:
      return {"ok": False, "payload": None, "results": [], "attempts": attempt,
              "error": got["error"]}
    payload = got["payload"]
    payload["section_key"] = section_key
    _drop_orphan_notes(payload)
    results = run_section_checks(payload, brief, draft)
    results.append(observation_floor_check(payload, brief, ex_ids))
    if CK.section_passes(results):
      return {"ok": True, "payload": payload, "results": results,
              "attempts": attempt, "error": None}
    fails = CK.failures(results)
    feedback = "\n".join("%s (%s): %s %s" % (r.rule_id, r.failure_code, r.detail,
                                             "; ".join(r.offenders[:5]))
                         for r in fails)
    last = {"ok": False, "payload": payload, "results": results,
            "attempts": attempt, "error": "checks_failed"}
  return last


def render_section_text(section_payload: Dict[str, Any], cat: FactCatalog) -> str:
  """Substitute every fact token through the one formatter and lay the
  paragraphs out. Note markers render as bracketed numbers; the docx renderer
  will style them as superscripts."""
  def _sub(m):
    f = cat.get_quiet(m.group(1))
    return f.render() if f is not None else m.group(0)

  paras: Dict[int, List[str]] = {}
  for s in section_payload.get("sentences") or []:
    p = int(s.get("paragraph") or 1)
    text = CK.FACT_TOKEN.sub(_sub, str(s.get("text") or ""))
    text = CK._SUPERSCRIPT_MARKER.sub(lambda m: "[%s]" % m.group(1), text)
    paras.setdefault(p, []).append(text)
  out = "\n\n".join(" ".join(paras[p]) for p in sorted(paras))
  notes = section_payload.get("notes") or []
  if notes:
    # the kind (SOURCE/BASIS) is machinery for the checks - the reader gets
    # the note text alone (Nick 2026-09-02: "BASIS" reads like a form field)
    out += "\n\n" + "\n".join(
      "[%s] %s" % (n.get("id"), CK.FACT_TOKEN.sub(_sub, str(n.get("text") or "")))
      for n in notes)
  return out
