"""THE CHECKS BEHIND THE RULES (2026-08-30).

Every rule in rules.py that claims enforcement names a callable here. Nick's
standard: "EVERY RULE NEEDS A CHECK BEHIND IT OR IT ISN'T A RULE. The debt
sheet is trustworthy because principal can't be a literal and R50 catches
frozen anchors - not because anyone was careful."

THE GOVERNING LAW OF THIS MODULE, confirmed by Nick 2026-08-30 and taken
directly from the CoInitialize bug of 2026-08-29:

    A CHECK THAT CANNOT RUN FAILS THE SECTION. IT NEVER PASSES BY DEFAULT.

That bug shipped for weeks because _recalc_workbook_via_excel_com returned
"unable to evaluate" on a worker thread and the caller read it as fine. Every
CheckResult therefore carries `executed`, and `section_passes()` treats
executed=False as a failure - not as a skip, not as a warning.

Nothing here writes prose, calls GPT, renders a chart or opens a document.
These are pure functions over text and structures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from . import rules as R

# The fact token, identical in shape to the intake side's proven one
# (fact_templates.py, CW-018) so a reader moving between them is never
# surprised: {{fact:some.key}}
FACT_TOKEN = re.compile(r"\{\{fact:([A-Za-z0-9_.-]+)\}\}")

# A bare numeral is anything numeric that is NOT inside a fact token. Rule 17
# turns on this: GPT may not compute, so any surviving digit is a computation
# we cannot trace. Ordinals written as words are fine; "Year 1" and "Q3" are
# structural labels, not quantities, and are allowed by name.
_ALLOWED_BARE_NUMERIC = re.compile(
  r"\b(?:year\s*[1-5]|y[1-5]|q[1-4]|quarter\s*(?:one|two|three|four))\b",
  re.IGNORECASE,
)
_ANY_DIGIT = re.compile(r"\d")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]{2,}\b")
_SUPERSCRIPT_MARKER = re.compile(r"\[\^(\d+)\]")


@dataclass
class CheckResult:
  rule_id: str
  executed: bool
  passed: bool
  failure_code: Optional[str] = None
  detail: str = ""
  offenders: List[str] = field(default_factory=list)

  @classmethod
  def could_not_run(cls, rule_id: str, why: str) -> "CheckResult":
    """The CoInitialize shape. Never a pass."""
    return cls(rule_id=rule_id, executed=False, passed=False,
               failure_code="writing_check_could_not_run",
               detail="check could not run: %s" % why)


def section_passes(results: Sequence[CheckResult]) -> bool:
  """A section is admitted only if every check RAN and every check PASSED."""
  if not results:
    return False
  return all(r.executed and r.passed for r in results)


def failures(results: Sequence[CheckResult]) -> List[CheckResult]:
  return [r for r in results if not (r.executed and r.passed)]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sentences(text: str) -> List[str]:
  return [s.strip() for s in _SENTENCE_SPLIT.split(str(text or "")) if s.strip()]


def _strip_fact_tokens(text: str) -> str:
  return FACT_TOKEN.sub(" ", str(text or ""))


def _strip_note_markers(text: str) -> str:
  """[^n] is the SANCTIONED notation R11 requires - it is not a typed number
  (R17) and must not glue sentences together for the length scan (R01). Found
  live on the first authored section, 2026-09-01: the S61 sentence failed R17
  on its own citation marker."""
  return _SUPERSCRIPT_MARKER.sub(" ", str(text or ""))


def _contains_any(text: str, needles: Iterable[str]) -> List[str]:
  low = str(text or "").lower()
  return [n for n in needles if n in low]


def _all_prose(section_payload: Dict[str, Any]) -> str:
  """Prose only. Notes are scanned separately because rule 3 must cover BOTH
  (Nick ruling C) and some checks legitimately apply to one and not the other."""
  parts = [str(s.get("text") or "") for s in section_payload.get("sentences") or []]
  return " ".join(parts)


def _all_notes_text(section_payload: Dict[str, Any]) -> str:
  return " ".join(str(n.get("text") or "") for n in section_payload.get("notes") or [])


# ---------------------------------------------------------------------------
# R03 - never name what we do not have           (prose AND notes)
# ---------------------------------------------------------------------------
def check_no_absence_language(section_payload: Dict[str, Any], **_: Any) -> CheckResult:
  rid = "R03"
  try:
    blob = _all_prose(section_payload) + " " + _all_notes_text(section_payload)
  except Exception as exc:
    return CheckResult.could_not_run(rid, str(exc)[:120])
  hits = _contains_any(blob, R.FORBIDDEN_ABSENCE_PHRASES)
  return CheckResult(rid, True, not hits,
                     R.rule(rid)["failure_code"] if hits else None,
                     "named a gap to the reader" if hits else "", hits)


# ---------------------------------------------------------------------------
# R04 - no machinery                             (span-scoped exception)
# ---------------------------------------------------------------------------
def check_no_machinery(section_payload: Dict[str, Any], **_: Any) -> CheckResult:
  rid = "R04"
  try:
    sentences = section_payload.get("sentences") or []
  except Exception as exc:
    return CheckResult.could_not_run(rid, str(exc)[:120])
  offenders: List[str] = []
  for s in sentences:
    if str(s.get("span") or "") in R.MACHINERY_EXCEPTION_SPANS:
      continue   # forecast-as-forecast is legal ONLY inside the basis paragraph
    offenders.extend(_contains_any(s.get("text"), R.FORBIDDEN_MACHINERY_TERMS))
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "exposed the machinery" if offenders else "",
                     sorted(set(offenders)))


# ---------------------------------------------------------------------------
# R17 - GPT MAY NOT COMPUTE  /  R06 - facts resolve  /  R18 - namespace scope
# ---------------------------------------------------------------------------
def check_no_computation(section_payload: Dict[str, Any],
                         business_name: Optional[str] = None,
                         **_: Any) -> CheckResult:
  """Any bare numeral outside a fact token is a computation we cannot trace.
  The literal business name is exempt: R15 REQUIRES the name, and a client
  whose name carries a digit ('Studio 54') must not fail R17 for complying -
  found live 2026-09-01 on 'Bluestem Grounds P6 Retest', where GPT dodging
  the name then tripped R05 instead."""
  rid = "R17"
  try:
    sentences = section_payload.get("sentences") or []
  except Exception as exc:
    return CheckResult.could_not_run(rid, str(exc)[:120])
  name_pat = None
  if business_name and _ANY_DIGIT.search(str(business_name)):
    name_pat = re.compile(re.escape(str(business_name)), re.IGNORECASE)
  offenders: List[str] = []
  for s in sentences:
    text = _strip_note_markers(_strip_fact_tokens(s.get("text")))
    if name_pat is not None:
      text = name_pat.sub(" ", text)
    residue = _ALLOWED_BARE_NUMERIC.sub(" ", text)
    if _ANY_DIGIT.search(residue):
      offenders.append(str(s.get("text"))[:90])
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "a number was typed rather than referenced" if offenders else "",
                     offenders)


def check_fact_tokens_resolve(section_payload: Dict[str, Any],
                              brief_facts: Optional[Dict[str, Any]] = None,
                              **_: Any) -> CheckResult:
  rid = "R06"
  if brief_facts is None:
    # No brief means the check cannot run. It does not mean the section is fine.
    return CheckResult.could_not_run(rid, "no brief fact catalogue supplied")
  offenders: List[str] = []
  for s in section_payload.get("sentences") or []:
    for key in FACT_TOKEN.findall(str(s.get("text") or "")):
      if key not in brief_facts:
        offenders.append(key)
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "fact token does not resolve to the brief" if offenders else "",
                     sorted(set(offenders)))


def check_namespace_scope(section_payload: Dict[str, Any], **_: Any) -> CheckResult:
  """Rule 18 as a namespace test: the body is annual, with two named
  quarterly exceptions. Charts are exempt - Nick ruled the annual rule governs
  the narrative, not the visuals."""
  rid = "R18"
  try:
    is_appendix = str(section_payload.get("section_key")) == "appendix"
  except Exception as exc:
    return CheckResult.could_not_run(rid, str(exc)[:120])
  if is_appendix:
    return CheckResult(rid, True, True, None, "appendix carries full quarterly detail")
  offenders: List[str] = []
  for s in section_payload.get("sentences") or []:
    for key in FACT_TOKEN.findall(str(s.get("text") or "")):
      if not R.namespace_allowed_in_body(key):
        offenders.append(key)
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "quarterly detail reached the narrative" if offenders else "",
                     sorted(set(offenders)))


# ---------------------------------------------------------------------------
# R14 - the three sentence classes + the density guard
# ---------------------------------------------------------------------------
def check_sentence_classes(section_payload: Dict[str, Any], **_: Any) -> CheckResult:
  rid = "R14"
  sentences = section_payload.get("sentences") or []
  if not sentences:
    return CheckResult.could_not_run(rid, "section carried no classified sentences")
  offenders: List[str] = []
  counts = {c: 0 for c in R.SENTENCE_CLASSES}
  for s in sentences:
    cls = str(s.get("class") or "").strip().upper()
    text = str(s.get("text") or "")
    if cls not in R.SENTENCE_CLASSES:
      offenders.append("untagged/unknown class: %s" % (text[:70],))
      continue
    counts[cls] += 1
    spec = R.CLASS_RULES[cls]
    # markers stripped for the digit scan; a marker in FRAMING still fails
    # below as a citation, which is the honest name for the offence
    if spec.get("forbids_digits") and _ANY_DIGIT.search(
        _strip_note_markers(_strip_fact_tokens(text))):
      offenders.append("FRAMING carries a digit: %s" % text[:70])
    if spec.get("forbids_digits") and FACT_TOKEN.search(text):
      offenders.append("FRAMING carries a fact token: %s" % text[:70])
    if spec.get("forbids_proper_nouns") and _PROPER_NOUN.search(
        re.sub(r"^\W*\w+", "", text)):   # ignore the sentence-initial word
      offenders.append("FRAMING carries a proper noun: %s" % text[:70])
    if spec.get("forbids_citations") and _SUPERSCRIPT_MARKER.search(text):
      offenders.append("FRAMING carries a citation: %s" % text[:70])
  total = sum(counts.values()) or 1
  for cls, guard in R.DENSITY_GUARD.items():
    share = counts[cls] / total
    if guard["min_share"] is not None and share < guard["min_share"]:
      offenders.append("%s share %.2f below floor %.2f" % (cls, share, guard["min_share"]))
    if guard["max_share"] is not None and share > guard["max_share"]:
      offenders.append("%s share %.2f above cap %.2f" % (cls, share, guard["max_share"]))
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "sentence-class or density violation" if offenders else "",
                     offenders)


# ---------------------------------------------------------------------------
# R05 - no fluff (specificity proxy; FRAMING exempt by Nick's ruling A)
# ---------------------------------------------------------------------------
# Place names too generic to identify a client - a token both roasters share
# catches nothing.
_GENERIC_PLACE_TOKENS = {"united states", "usa", "america", "north america"}
_LEGAL_SUFFIX = re.compile(
  r"[,.]?\s*(llc|l\.l\.c\.|inc\.?|incorporated|corp\.?|corporation|co\.?|ltd\.?|llp|pllc|p\.c\.)\s*$",
  re.IGNORECASE)
_PLACE_NAME = re.compile(r"\b([A-Z][a-z]{3,}(?: [A-Z][a-z]{3,})*)\b")


def client_tokens_for_draft(draft: Dict[str, Any],
                            extra: Optional[Iterable[str]] = None) -> Set[str]:
  """THE PRODUCER FOR R05 (Nick 2026-09-01). check_specificity fails closed
  without a token set, and until today nothing built one - the section would
  have failed R05 on day one. Tokens are the things only THIS client's plan
  can say: the business name (with and without its legal suffix, plus its
  distinctive first word), the named people, and the place names in the stated
  coverage. Deliberately NOT the NAICS title or LOB nouns - two businesses in
  one trade share those, and a shared token catches nothing."""
  import json as _json

  def _j(v):
    if isinstance(v, (dict, list)):
      return v
    try:
      return _json.loads(v) if v else {}
    except Exception:
      return {}

  toks: Set[str] = set()
  d = draft or {}
  name = str(d.get("business_name") or "").strip()
  if name:
    toks.add(name)
    stripped = _LEGAL_SUFFIX.sub("", name).strip()
    if stripped:
      toks.add(stripped)
      first = stripped.split()[0]
      if len(first) >= 4 and first.lower() != "the":
        toks.add(first)
  for p in (_j(d.get("people_json")).get("people") or []):
    if isinstance(p, dict):
      full = str(p.get("full_name") or "").strip()
      if full:
        toks.add(full)
        last = full.split()[-1]
        if len(last) >= 4:
          toks.add(last)
  cov = str(_j(d.get("operating_model_json")).get("geographic_coverage") or "")
  for m in _PLACE_NAME.finditer(cov):
    if m.group(1).lower() not in _GENERIC_PLACE_TOKENS:
      toks.add(m.group(1))
  for t in (extra or ()):
    if t and str(t).strip():
      toks.add(str(t).strip())
  return {t for t in toks if len(t) >= 4}


def check_specificity(section_payload: Dict[str, Any],
                      client_tokens: Optional[Set[str]] = None,
                      **_: Any) -> CheckResult:
  rid = "R05"
  if client_tokens is None:
    return CheckResult.could_not_run(rid, "no client token set supplied")
  offenders: List[str] = []
  for s in section_payload.get("sentences") or []:
    cls = str(s.get("class") or "").upper()
    if R.CLASS_RULES.get(cls, {}).get("exempt_from_swap_test"):
      continue     # FRAMING is connective tissue, capped rather than swap-tested
    text = str(s.get("text") or "")
    if FACT_TOKEN.search(text):
      continue     # a referenced figure is client-specific by construction
    low = text.lower()
    if not any(tok.lower() in low for tok in client_tokens if tok):
      offenders.append(text[:90])
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "sentence survives the competitor swap" if offenders else "",
                     offenders)


# ---------------------------------------------------------------------------
# R15 - voice   /   R16 - number style
# ---------------------------------------------------------------------------
def check_voice(section_payload: Dict[str, Any],
                business_name: Optional[str] = None, **_: Any) -> CheckResult:
  rid = "R15"
  try:
    blob = _all_prose(section_payload)
  except Exception as exc:
    return CheckResult.could_not_run(rid, str(exc)[:120])
  offenders: List[str] = []
  for pron in R.FORBIDDEN_PRONOUNS:
    if re.search(r"\b%s\b" % re.escape(pron), blob, re.IGNORECASE):
      offenders.append(pron)
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "first or second person in the narrative" if offenders else "",
                     offenders)


def check_number_style(section_payload: Dict[str, Any], **_: Any) -> CheckResult:
  """Rule 16 is enforced by construction - one formatter renders every figure.
  What remains checkable in the GPT output is the hedging ban: no
  'approximately' ON a figure that exists. ON, not NEAR: 'built around a
  weekly route' is idiom, not a hedge, and failed this check live on
  2026-09-01 - so only a hedge word immediately preceding a fact token
  offends."""
  rid = "R16"
  hedge_before_token = re.compile(
    r"\b(?:%s)\s+(?:the\s+|its\s+|a\s+|an\s+)?\{\{fact:" %
    "|".join(re.escape(h) for h in R.HEDGE_WORDS), re.IGNORECASE)
  offenders: List[str] = []
  for s in section_payload.get("sentences") or []:
    text = str(s.get("text") or "")
    if not FACT_TOKEN.search(text):
      continue
    m = hedge_before_token.search(text)
    if m:
      offenders.append("%s -> %s" % (m.group(0)[:30], text[:60]))
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "hedged a grounded figure" if offenders else "",
                     offenders)


# ---------------------------------------------------------------------------
# R11 - sources & notes
# ---------------------------------------------------------------------------
def check_notes(section_payload: Dict[str, Any],
                brief_facts: Optional[Dict[str, Any]] = None,
                **_: Any) -> CheckResult:
  rid = "R11"
  notes = section_payload.get("notes")
  if notes is None:
    return CheckResult.could_not_run(rid, "section carried no notes structure")
  offenders: List[str] = []
  declared = {str(n.get("id")) for n in notes}
  referenced: Set[str] = set()
  marker_kinds: Dict[str, Set[str]] = {}
  for s in section_payload.get("sentences") or []:
    text = str(s.get("text") or "")
    referenced.update(_SUPERSCRIPT_MARKER.findall(text))
    if brief_facts is not None:
      kinds = {str((brief_facts.get(k) or {}).get("note_kind") or "")
               for k in FACT_TOKEN.findall(text)}
      for mid in _SUPERSCRIPT_MARKER.findall(text):
        marker_kinds.setdefault(mid, set()).update(kinds)
  if brief_facts is not None:
    # Ruling E holds at the note level too: a SOURCE note is legal only where
    # a referenced fact actually carries SOURCE provenance. Found live
    # 2026-09-01 - GPT dressed a BDS (BASIS) fact as a Census SOURCE with an
    # invented vintage, and the structural checks alone let it through.
    for n in notes:
      if str(n.get("kind") or "").upper() == R.NOTE_KIND_SOURCE:
        if R.NOTE_KIND_SOURCE not in marker_kinds.get(str(n.get("id")), set()):
          offenders.append("note %s claims SOURCE but no referenced fact "
                           "carries SOURCE provenance" % n.get("id"))
  for missing in sorted(referenced - declared):
    offenders.append("marker %s has no note" % missing)
  for orphan in sorted(declared - referenced):
    offenders.append("note %s is never referenced" % orphan)
  for n in notes:
    kind = str(n.get("kind") or "").upper()
    if kind not in R.NOTE_KINDS:
      offenders.append("note %s has kind %r" % (n.get("id"), kind))
      continue
    if kind == R.NOTE_KIND_SOURCE:
      for req in R.SOURCE_NOTE_REQUIRES:
        if not str(n.get(req) or "").strip():
          offenders.append("SOURCE note %s lacks %s" % (n.get("id"), req))
    offenders.extend(_contains_any(n.get("text"), R.FORBIDDEN_ATTRIBUTION_PHRASES))
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "note structure invalid" if offenders else "", offenders)


# ---------------------------------------------------------------------------
# R08/R13 - charts and section emission
# ---------------------------------------------------------------------------
def check_chart_registry(emitted_charts: Optional[Sequence[Dict[str, Any]]] = None,
                         **_: Any) -> CheckResult:
  """Registry ids only, and figure numbers must be CONTIGUOUS from 1 - Nick's
  addition: a chart whose data is absent is omitted silently and the figures
  renumber, so a gap in the numbering means something referenced a figure that
  is not there."""
  rid = "R08"
  if emitted_charts is None:
    return CheckResult.could_not_run(rid, "no emitted-chart list supplied")
  known = {c["key"] for c in R.CHART_REGISTRY}
  offenders = [str(c.get("key")) for c in emitted_charts if c.get("key") not in known]
  numbers = [int(c.get("figure_number") or 0) for c in emitted_charts]
  if numbers and sorted(numbers) != list(range(1, len(numbers) + 1)):
    offenders.append("figure numbers not contiguous from 1: %s" % sorted(numbers))
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "chart off registry or misnumbered" if offenders else "", offenders)


def check_section_emission(emitted_sections: Optional[Sequence[str]] = None,
                           triggers: Optional[Dict[str, bool]] = None,
                           overrides: Optional[Dict[str, bool]] = None,
                           **_: Any) -> CheckResult:
  """Omission by CHOICE alongside the data condition (Nick, 2026-08-31).
  `overrides` is the client's explicit map: False excludes an omissible
  section, True is only honoured where the data condition already holds.
  Disclosures (omissible=False) is present under EVERY configuration."""
  rid = "R13"
  if emitted_sections is None or triggers is None:
    return CheckResult.could_not_run(rid, "no emitted-section list or trigger map supplied")
  ov = overrides or {}
  offenders: List[str] = []
  emitted = list(emitted_sections)
  for spec in R.SECTION_REGISTRY:
    key, is_core, trig = spec["key"], spec["core"], spec.get("trigger")
    omissible = spec.get("omissible", True)
    data_ok = is_core or triggers.get(trig, False)
    chosen_off = ov.get(key) is False and omissible
    expected = data_ok and not chosen_off
    if not omissible and key not in emitted:
      offenders.append("locked section missing: %s (not omissible under any configuration)" % key)
    elif expected and key not in emitted:
      offenders.append("section missing without an explicit exclusion: %s" % key)
    elif not data_ok and key in emitted:
      offenders.append("section %s emitted without its data condition (%s) - an explicit ON cannot conjure it" % (key, trig))
    elif chosen_off and key in emitted:
      offenders.append("section %s emitted despite an explicit exclusion" % key)
  order = [s["key"] for s in sorted(R.SECTION_REGISTRY, key=lambda s: s["order"])]
  if emitted != [k for k in order if k in emitted]:
    offenders.append("sections emitted out of registry order")
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "section emission invalid" if offenders else "", offenders)


# ---------------------------------------------------------------------------
# R19/R20 - basis paragraph and proportion
# ---------------------------------------------------------------------------
def check_basis_of_projections(document_spans: Optional[Sequence[str]] = None,
                               **_: Any) -> CheckResult:
  rid = "R19"
  if document_spans is None:
    return CheckResult.could_not_run(rid, "no span list supplied")
  n = sum(1 for s in document_spans if s == R.BASIS_OF_PROJECTIONS["span_key"])
  ok = n == R.BASIS_OF_PROJECTIONS["max_occurrences"]
  return CheckResult(rid, True, ok,
                     R.rule(rid)["failure_code"] if not ok else None,
                     "basis paragraph appears %d times, expected exactly 1" % n if not ok else "")


def check_proportion(section_pages: Optional[Dict[str, float]] = None,
                     **_: Any) -> CheckResult:
  """ADVISORY BY DESIGN. Nick: targets, not truncation - they flag a section
  for review, they never cut it. So this returns passed=True and reports the
  out-of-band sections as offenders for the review queue."""
  rid = "R20"
  if section_pages is None:
    return CheckResult.could_not_run(rid, "no page estimate supplied")
  flagged: List[str] = []
  for spec in R.SECTION_REGISTRY:
    est = section_pages.get(spec["key"])
    if est is None or spec["pages_min"] is None:
      continue
    if est < spec["pages_min"] or est > spec["pages_max"]:
      flagged.append("%s ~%.1fpp (target %s-%s)"
                     % (spec["key"], est, spec["pages_min"], spec["pages_max"]))
  body = sum(v for k, v in section_pages.items() if k in set(R.body_section_keys()))
  if body and not (R.BODY_PAGES_MIN <= body <= R.BODY_PAGES_MAX):
    flagged.append("body ~%.1fpp (target %d-%d)" % (body, R.BODY_PAGES_MIN, R.BODY_PAGES_MAX))
  return CheckResult(rid, True, True, None,
                     "flagged for review; nothing truncated", flagged)


# ---------------------------------------------------------------------------
# proxies that need a corpus or a rendered document
# ---------------------------------------------------------------------------
def check_cross_plan_similarity(section_payload: Dict[str, Any],
                                corpus_ngrams: Optional[Set[str]] = None,
                                **_: Any) -> CheckResult:
  rid = "R02"
  if corpus_ngrams is None:
    return CheckResult.could_not_run(rid, "no same-NAICS corpus supplied")
  n = R.SIMILARITY_GUARD["ngram_size"]
  words: List[str] = []
  for s in section_payload.get("sentences") or []:
    if str(s.get("span") or "") in R.BOILERPLATE_SPANS:
      continue     # Nick ruling D - our own template must not trip this
    words.extend(re.findall(r"[a-z0-9']+", str(s.get("text") or "").lower()))
  grams = {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}
  if not grams:
    return CheckResult.could_not_run(rid, "no comparable prose in section")
  share = len(grams & corpus_ngrams) / len(grams)
  ok = share <= R.SIMILARITY_GUARD["max_overlap_share"]
  return CheckResult(rid, True, ok,
                     R.rule(rid)["failure_code"] if not ok else None,
                     "%.1f%% of %d-grams seen in a same-NAICS plan" % (share * 100, n),
                     [])


def check_readability(section_payload: Dict[str, Any], **_: Any) -> CheckResult:
  rid = "R01"
  sents = _sentences(_strip_note_markers(_strip_fact_tokens(_all_prose(section_payload))))
  if not sents:
    return CheckResult.could_not_run(rid, "no prose to measure")
  long_ones = [s[:80] for s in sents if len(s.split()) > 45]
  return CheckResult(rid, True, not long_ones,
                     R.rule(rid)["failure_code"] if long_ones else None,
                     "sentence length out of band" if long_ones else "", long_ones)


def check_context_present(section_payload: Dict[str, Any], **_: Any) -> CheckResult:
  rid = "R07"
  if str(section_payload.get("section_key")) != "market_and_industry":
    return CheckResult(rid, True, True, None, "not applicable to this section")
  keys: Set[str] = set()
  for s in section_payload.get("sentences") or []:
    keys.update(FACT_TOKEN.findall(str(s.get("text") or "")))
  has_industry = any(k.startswith(R.NS_INDUSTRY + ".") for k in keys)
  has_market = any(k.startswith(R.NS_MARKET + ".") for k in keys)
  ok = has_industry and has_market
  return CheckResult(rid, True, ok,
                     R.rule(rid)["failure_code"] if not ok else None,
                     "" if ok else "industry and economic context not both present")


def check_source_family_coverage(section_payload: Dict[str, Any],
                                 min_families: int = 2, **_: Any) -> CheckResult:
  """R09 is SOFT. This proxy only proves several source families were touched -
  it cannot show they were reasoned across rather than concatenated."""
  rid = "R09"
  fams: Set[str] = set()
  for s in section_payload.get("sentences") or []:
    for k in FACT_TOKEN.findall(str(s.get("text") or "")):
      fams.add(k.split(".", 1)[0])
  ok = len(fams) >= min_families
  return CheckResult(rid, True, ok,
                     R.rule(rid)["failure_code"] if not ok else None,
                     "touched %d source families" % len(fams), sorted(fams))


def check_structure_and_repetition(**kwargs: Any) -> CheckResult:
  """R12 is the conjunction of the section registry (R13) and the similarity
  guard (R02); it holds only if both ran and both passed."""
  rid = "R12"
  parts = [kwargs.get("section_emission_result"), kwargs.get("similarity_result")]
  if any(p is None for p in parts):
    return CheckResult.could_not_run(rid, "structure or similarity result absent")
  ok = all(p.executed and p.passed for p in parts)
  return CheckResult(rid, True, ok,
                     R.rule(rid)["failure_code"] if not ok else None,
                     "" if ok else "structure or repetition violation")


# ---- document-level checks: these run on the RENDERED docx, not on prose ----
def check_footer_and_run_id(document_probe: Optional[Dict[str, Any]] = None,
                            **_: Any) -> CheckResult:
  rid = "R21"
  if document_probe is None:
    return CheckResult.could_not_run(rid, "no rendered-document probe supplied")
  offenders: List[str] = []
  if not document_probe.get("footer_matches_template"):
    offenders.append("footer does not match the template")
  for where in R.RUN_ID_FORBIDDEN_IN:
    if document_probe.get("run_id_in_%s" % where):
      offenders.append("run id appears in the %s" % where)
  if not document_probe.get("run_id_in_appendix"):
    offenders.append("run id absent from the appendix")
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "version stamp violation" if offenders else "", offenders)


def check_document_craft(document_probe: Optional[Dict[str, Any]] = None,
                         **_: Any) -> CheckResult:
  rid = "R22"
  if document_probe is None:
    return CheckResult.could_not_run(rid, "no rendered-document probe supplied")
  offenders: List[str] = []
  if document_probe.get("direct_formatted_runs"):
    offenders.append("%d directly formatted runs (styles bypassed)"
                     % document_probe["direct_formatted_runs"])
  if not document_probe.get("uses_real_styles"):
    offenders.append("headings/tables are not real Word styles")
  if document_probe.get("font_families_used", 0) > 2:
    offenders.append("more than one font pair in use")
  if document_probe.get("table_styles_used", 0) > 1:
    offenders.append("more than one table style in use")
  for fig in document_probe.get("figures_without_caption") or []:
    offenders.append("figure %s has no caption" % fig)
  for fig in document_probe.get("figures_without_cross_reference") or []:
    offenders.append("figure %s is never referenced in the text" % fig)
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "document craft violation" if offenders else "", offenders)


def check_editable(document_probe: Optional[Dict[str, Any]] = None,
                   **_: Any) -> CheckResult:
  rid = "R23"
  if document_probe is None:
    return CheckResult.could_not_run(rid, "no rendered-document probe supplied")
  offenders: List[str] = []
  if document_probe.get("text_boxes"):
    offenders.append("%d text boxes" % document_probe["text_boxes"])
  # Rule 23 as narrowed (2026-08-30): anchored images with square/tight wrap
  # are PERMITTED - they flow with their paragraph. Absolute positioning
  # (no wrap, behind-text, through) is what fights an editor and is banned.
  ap = document_probe.get("absolutely_positioned")
  if ap is None:
    return CheckResult.could_not_run(rid, "probe lacks anchor classification")
  if ap:
    offenders.append("%d absolutely positioned shapes" % ap)
  return CheckResult(rid, True, not offenders,
                     R.rule(rid)["failure_code"] if offenders else None,
                     "document would fight an editor" if offenders else "", offenders)


# The registry the verifier walks. A rule with a check MUST appear here, and
# tests/test_writing_phase_rules.py fails if one does not - that is what stops
# a rule quietly losing its enforcement later.
CHECK_REGISTRY = {
  "check_readability": check_readability,
  "check_cross_plan_similarity": check_cross_plan_similarity,
  "check_no_absence_language": check_no_absence_language,
  "check_no_machinery": check_no_machinery,
  "check_specificity": check_specificity,
  "check_fact_tokens_resolve": check_fact_tokens_resolve,
  "check_context_present": check_context_present,
  "check_chart_registry": check_chart_registry,
  "check_source_family_coverage": check_source_family_coverage,
  "check_notes": check_notes,
  "check_structure_and_repetition": check_structure_and_repetition,
  "check_section_emission": check_section_emission,
  "check_sentence_classes": check_sentence_classes,
  "check_voice": check_voice,
  "check_number_style": check_number_style,
  "check_no_computation": check_no_computation,
  "check_namespace_scope": check_namespace_scope,
  "check_basis_of_projections": check_basis_of_projections,
  "check_proportion": check_proportion,
  "check_footer_and_run_id": check_footer_and_run_id,
  "check_document_craft": check_document_craft,
  "check_editable": check_editable,
}
