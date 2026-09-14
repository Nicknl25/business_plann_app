"""DOOR C - the persist door. EVERY write, EVERY path, ONE place.

Nick 2026-09-12: "The intake agent runs everywhere. It ran on one code path.
Not financials - the stage where revenue, rent, overhead and payroll get
captured, where it made zero calls across forty turns. Not the coherence
apply, where an option's click rewrote my stated revenue. Every stage.
Every path a value can land through. And tell me how you know you've found
them all - a structural argument, the way you did for the payroll anchor."

THE STRUCTURAL ARGUMENT. A turn's writes to the four intake sections
(operating_model_json, target_market_json, people_json, financials_json)
reach the database through exactly one function: intake_consult_draft.
append_messages. Every other UPDATE of intake_consult_drafts touches
status, the submitted stamp, planning columns, repair guidance or the
marketing schedule - never a section (tests pin this by reading the module).
So whatever path a value takes inside a turn - the generic router patch,
the financials handler's own normaliser, the inference door, a coherence
option's apply, custom prices, a retention answer, the people door - it
lands here, where the pre-turn row and the post-turn sections are both in
hand. This door diffs them. It does not depend on finding call sites.

WHAT IT DOES with each changed leaf. ORIGIN is one of the four authorised
origins (provenance.py, now wired: router_patch - door A allowed it this
turn; option_pick - the walk's lever-writes record; guard_rewrite;
estimator_baseline) or none. VERDICT is what the guard did:
  authorised        an authorised origin - recorded
  refused           a COST option's write to current_revenue (Nick:
                    "$4,600,000 became $3,449,999.99 from a marketing
                    decision") - the stated value restored, the lever write
                    removed, the client reads a receipt
  app_arithmetic    not a client write: the app's own bookkeeping, a roster
                    row (the people door's), or arithmetic on a figure a door
                    or the walk authorised (its monthly/annual twin) - recorded
  reviewed_allowed  a STATED-FACT field with no origin, sent to door A's model
                    against the turn's own words - even when the number is in
                    those words (the van lease was "2,400 a month" in the
                    client's words and landed on rent) - and let stand
  asked             ALSO how a model rewrite lands here now (Nick 2026-09-13):
                    the persist door does not correct blind - the 09-12 proof
                    run showed it moving a principal onto interest with the
                    question out of view - so an opinion that a value is on the
                    wrong field becomes a QUESTION, which is what puts the
                    question back in view. There is no longer a category that
                    records a wrong value and lets it land.
  unguarded         the model could not be reached; the write stands, loudly
One row per persisted turn goes to intake_guard_actions (action
'turn_review') whether or not anything changed - the persona gate prints
that table, and a turn without a row is a FAIL. Fail OPEN, loudly.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.intake_guard import provenance as _prov

logger = logging.getLogger(__name__)

SECTIONS = ("ops", "market", "people", "financials")
_MAX_TEXT = 200
_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
_MILLION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m\b|mm\b|million)", re.I)
_THOUSAND_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:k\b|thousand)", re.I)
COST_LEVER_FIELDS = frozenset({"other_opex_absolute", "other_operating_expense", "marketing_total_year1",
                               "monthly_rent_expense", "baseline_payroll_year1", "payroll_adjustment",
                               "current_cogs", "cogs_total_year1", "cogs_percent_of_revenue"})


def enabled() -> bool:
  import os
  return (os.getenv("INTAKE_GUARD_ENABLED") or "1").strip().lower() not in ("0", "false", "no", "off")


def _f(v: Any) -> Optional[float]:
  if isinstance(v, bool):
    return None
  if isinstance(v, (int, float)):
    return float(v)
  if isinstance(v, str):
    try:
      return float(v.replace(",", "").replace("$", "").strip())
    except ValueError:
      return None
  return None


def leaves(obj: Any, prefix: str = "") -> Dict[str, Any]:
  """Every leaf under a section: numbers as floats, bools, strings cut to
  200 chars. Private keys (leading underscore) are the app's own state
  (_coherence, _guard, ...) and are never a client write."""
  out: Dict[str, Any] = {}
  if isinstance(obj, dict):
    for k, v in obj.items():
      if str(k).startswith("_"):
        continue
      out.update(leaves(v, f"{prefix}.{k}" if prefix else str(k)))
  elif isinstance(obj, list):
    for i, v in enumerate(obj):
      out.update(leaves(v, f"{prefix}[{i}]"))
  else:
    if not prefix:
      return out
    if isinstance(obj, bool) or obj is None:
      out[prefix] = obj
    else:
      fv = _f(obj) if not isinstance(obj, str) or _NUM_RE.fullmatch(obj.replace(",", "").strip() or "x") else None
      out[prefix] = fv if fv is not None else (str(obj)[:_MAX_TEXT] if isinstance(obj, str) else obj)
  return out


def diff_sections(pre: Dict[str, Any], post: Dict[str, Any]) -> List[Dict[str, Any]]:
  """[{path, from, to}] over the four sections; a section absent from post
  was not written this turn and is skipped."""
  changes: List[Dict[str, Any]] = []
  for sec in SECTIONS:
    if post.get(sec) is None:
      continue
    a = leaves(pre.get(sec) or {}, sec)
    b = leaves(post.get(sec) or {}, sec)
    for path in sorted(set(a) | set(b)):
      va, vb = a.get(path), b.get(path)
      # AN EMPTY VALUE IS NOT A WRITE (CW-070 clone e7120169, 2026-09-14): a router
      # emitting geographic_coverage "" where nothing was stored became a "write",
      # went to the model as an unreviewed fact, and door C asked her about it -
      # with her whole capacity sentence quoted as the reason. Absent, null and
      # blank all mean nothing was said.
      if (va is None or (isinstance(va, str) and not va.strip())) and (vb is None or (isinstance(vb, str) and not vb.strip())):
        continue
      if path in a and path in b:
        fa, fb = _f(va), _f(vb)
        # recomputation drift (31,937.92 vs 31,937.864) is not a write
        same = (abs(fa - fb) <= max(0.005, abs(fb) * 1e-3)) if (fa is not None and fb is not None) else (va == vb)
        if same:
          continue
      changes.append({"path": path, "from": va if path in a else None, "to": vb if path in b else None,
                      "added": path not in a, "removed": path not in b})
  return changes


_ROSTER_RE = re.compile(r"^(people\.people\[|financials\.payroll_basis_people_roles\[|people\.inferred_roles\[)")
_REWRITABLE_RE = re.compile(r"^(financials|ops)\.[a-z_0-9]+$")   # scalar stated facts only, no rows


_ROSTER_RE = re.compile(r"^(people\.people\[|financials\.payroll_basis_people_roles\[|people\.inferred_roles\[)")
_REWRITABLE_RE = re.compile(r"^(financials|ops)\.[a-z_0-9]+$")   # scalar stated facts only, no rows


def _leaf_name(path: str) -> str:
  return re.sub(r"\[\d+\]$", "", str(path).split(".")[-1])


from client_intake_and_finmo.reader_log import reads_client_words  # noqa: E402 - one-reader step 1b


@reads_client_words("door_c_numbers_in_words")
def numbers_in_words(text: str) -> List[float]:
  """Every figure the client said, with 'million'/'k' expanded."""
  found: List[float] = []
  t = str(text or "")
  for m in _MILLION_RE.finditer(t):
    try:
      found.append(float(m.group(1)) * 1_000_000)
    except ValueError:
      pass
  for m in _THOUSAND_RE.finditer(t):
    try:
      found.append(float(m.group(1)) * 1_000)
    except ValueError:
      pass
  for m in _NUM_RE.finditer(t):
    try:
      found.append(float(m.group(0).replace(",", "")))
    except ValueError:
      pass
  return found


def _equiv(v: float) -> Tuple[float, ...]:
  return (v, v * 12.0, v / 12.0, v * 4.0, v / 4.0, v * 3.0, v / 3.0, v * 52.0, v / 52.0)


def _close(a: float, b: float) -> bool:
  return abs(a - b) <= max(0.51, abs(b) * 0.002)


def _in_words(value: Any, words_numbers: List[float]) -> bool:
  fv = _f(value)
  if fv is None or fv == 0:
    return False
  return any(_close(e, w) for w in words_numbers for e in _equiv(fv))


def _literal_in_words(value: Any, words_numbers: List[float]) -> bool:
  fv = _f(value)
  return fv is not None and fv != 0 and any(_close(fv, w) for w in words_numbers)


def lever_writes_delta(pre_fin: Dict[str, Any], post_fin: Dict[str, Any]) -> Dict[str, Any]:
  """The lever writes this turn ADDED or MOVED (post minus pre), keyed as the
  walk records them ('field' or 'ops:<product>:<field>')."""
  a = ((pre_fin or {}).get("_coherence") or {}).get("_lever_writes") or {}
  b = ((post_fin or {}).get("_coherence") or {}).get("_lever_writes") or {}
  out: Dict[str, Any] = {}
  for k, w in b.items():
    if not isinstance(w, dict):
      continue
    pw = a.get(k) if isinstance(a.get(k), dict) else None
    if pw is None or _f(pw.get("to")) != _f(w.get("to")):
      out[k] = w
  return out


@reads_client_words("door_c_classify")
def classify(changes: List[Dict[str, Any]], *, allowed_patch: Dict[str, Any], lever_delta: Dict[str, Any],
             guard_rewrites: List[str], user_text: str) -> List[Dict[str, Any]]:
  words = numbers_in_words(user_text)
  # arithmetic on the client's own figures is theirs too: the sum of any two
  # or of all of them (two wages -> the team's payroll), in any common basis
  _w = [w for w in words if w > 0][:8]
  for i in range(len(_w)):
    for j in range(i + 1, len(_w)):
      words.append(_w[i] + _w[j])
  if len(_w) > 2:
    words.append(sum(_w))
  explained_numbers: List[float] = list(words)
  for k, w in (lever_delta or {}).items():
    fv = _f((w or {}).get("to")) if isinstance(w, dict) else None
    if fv is not None:
      explained_numbers.append(fv)
  for v in (allowed_patch or {}).values():
    fv = _f(v)
    if fv is not None:
      explained_numbers.append(fv)
  out: List[Dict[str, Any]] = []
  for c in changes:
    path, leaf = c["path"], _leaf_name(c["path"])
    # ORIGIN is one of the four authorised origins or None - nothing else.
    # VERDICT is what the guard did with the leaf.
    origin = _prov.origin_of(path, allowed_patch=allowed_patch, lever_writes=lever_delta, guard_rewrites=guard_rewrites)
    stated = _prov.is_stated_fact(path)
    verdict = None
    if origin is not None:
      verdict = "authorised"
    elif _ROSTER_RE.match(path):
      # the roster is the people door's (door A on the router path reviews it
      # row by row); a persist-time model moving values between rows lost a
      # named wage on the first proof run. Recorded, never reviewed here.
      verdict = "app_arithmetic"
    elif _f(c.get("to")) is not None and any(_close(e, n) for n in explained_numbers if n not in words for e in _equiv(_f(c["to"]))):
      verdict = "app_arithmetic"   # arithmetic on a figure a door or the walk authorised this turn
    elif not stated:
      verdict = "app_arithmetic"   # the app's own bookkeeping, or a non-stated leaf echoing the client's figure
    out.append({**c, "leaf": leaf, "origin": origin, "verdict": verdict, "stated_fact": stated})
  # A STATED FACT IS REVIEWED BY THE MODEL EVEN WHEN THE NUMBER IS IN THE
  # CLIENT'S WORDS - the van lease was "2,400 a month" in their words and it
  # landed on rent. Only its monthly/annual twin in the same turn is spared:
  # the base leaf (the figure as the client said it) carries the review.
  pending = [c for c in out if c["verdict"] is None]
  for c in pending:
    fv = _f(c.get("to"))
    if fv is None:
      c["verdict"] = "unreviewed"
      continue
    base = None
    for o in pending:
      if o is c or _f(o.get("to")) is None:
        continue
      ov = _f(o["to"])
      # the base is the figure AS THE CLIENT SAID IT (literally); the twin is its multiple
      if any(_close(e, ov) for e in _equiv(fv)[1:]) and _literal_in_words(ov, words) and not _literal_in_words(fv, words):
        base = o
        break
    c["verdict"] = "app_arithmetic" if base is not None else "unreviewed"
  return out


def _get_path(section_json: Any, path_in_section: str) -> Any:
  """Read a leaf by 'a.b[2].c' inside a section dict; None when not walkable."""
  cur: Any = section_json
  for tok in re.findall(r"[^.\[\]]+|\[\d+\]", path_in_section):
    if tok.startswith("["):
      idx = int(tok[1:-1])
      if not isinstance(cur, list) or idx >= len(cur):
        return None
      cur = cur[idx]
    else:
      if not isinstance(cur, dict):
        return None
      cur = cur.get(tok)
  return cur


_PERIOD_DEFAULTS = {"weekly": 52.0, "monthly": 12.0, "annual": 1.0, "yearly": 1.0, "per year": 1.0}
_MAX_PERIODS_FOR = {"monthly": 12.0, "weekly": 53.0}


def mark_cadence_defaults(classified: List[Dict[str, Any]], post: Dict[str, Any]) -> List[Dict[str, Any]]:
  """A DEFAULT IS NOT A FIGURE SHE SAID (CW-070, draft 71d4e505, 2026-09-14). The app
  moved a monthly row's period count from the weekly default 52 to the monthly default
  12; door C sent that to the model as a stated fact with no origin, the model judged
  it an overwrite, and the old default was held back - a question with no release,
  and 52 months a year in the store. A period count the normaliser itself wrote (the
  row carries the cadence mark and the value is that cadence's default) is the app's
  own arithmetic, never reviewed or held."""
  for c in classified:
    if _leaf_name(c.get("path") or "") != "operating_periods_per_year" or c.get("verdict") not in (None, "unreviewed"):
      continue
    sec, _, rest = str(c["path"]).partition(".")
    marker_path = (rest.rsplit(".", 1)[0] + "." if "." in rest else "") + "_periods_default_for"
    mark = str(_get_path(post.get(sec) or {}, marker_path) or "")
    to = _f(c.get("to"))
    if mark and to is not None and abs(to - _PERIOD_DEFAULTS.get(mark, -1.0)) <= 1e-9:
      c["verdict"] = "app_arithmetic"
      c["note"] = "the %s cadence's default period count, written by the app" % mark
      continue
    # NOTHING IMPOSSIBLE IS HELD BACK (CW-070 clone 703dd03f, 2026-09-14): the row was
    # monthly with 52 periods; the turn wrote 12, door C questioned the move and restored
    # the 52 until answered - putting back a count the row's own cadence cannot hold,
    # after the normaliser had cleared it. Moving a period count OFF an impossible value
    # is arithmetic; there is nothing valid to hold.
    cadence_path = (rest.rsplit(".", 1)[0] + "." if "." in rest else "") + "unit_cadence"
    cadence = str(_get_path(post.get(sec) or {}, cadence_path) or "").strip().lower()
    frm = _f(c.get("from"))
    limit = _MAX_PERIODS_FOR.get(cadence)
    if limit is not None and frm is not None and frm > limit + 1e-9 and (to is None or to <= limit + 1e-9):
      c["verdict"] = "app_arithmetic"
      c["note"] = "a %s row cannot hold %g periods a year; moving off it is not a figure to question" % (cadence, frm)
  return classified


def _set_path(section_json: Dict[str, Any], path_in_section: str, value: Any) -> bool:
  """Set a leaf by 'a.b[2].c' inside a section dict. False when the path is
  not walkable (then nothing is changed)."""
  tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path_in_section)
  cur: Any = section_json
  for i, tok in enumerate(tokens):
    last = i == len(tokens) - 1
    if tok.startswith("["):
      idx = int(tok[1:-1])
      if not isinstance(cur, list) or idx >= len(cur):
        return False
      if last:
        cur[idx] = value
        return True
      cur = cur[idx]
    else:
      if not isinstance(cur, dict):
        return False
      if last:
        cur[tok] = value
        return True
      if tok not in cur:
        return False
      cur = cur[tok]
  return False


def _del_path(section_json: Dict[str, Any], path_in_section: str) -> bool:
  tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path_in_section)
  cur: Any = section_json
  for i, tok in enumerate(tokens):
    last = i == len(tokens) - 1
    if tok.startswith("["):
      idx = int(tok[1:-1])
      if not isinstance(cur, list) or idx >= len(cur):
        return False
      if last:
        cur[idx] = None
        return True
      cur = cur[idx]
    else:
      if not isinstance(cur, dict) or tok not in cur:
        return False
      if last:
        cur.pop(tok, None)
        return True
      cur = cur[tok]
  return False


def _del_path(section_json: Dict[str, Any], path_in_section: str) -> bool:
  tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path_in_section)
  cur: Any = section_json
  for i, tok in enumerate(tokens):
    last = i == len(tokens) - 1
    if tok.startswith("["):
      idx = int(tok[1:-1])
      if not isinstance(cur, list) or idx >= len(cur):
        return False
      if last:
        cur[idx] = None
        return True
      cur = cur[idx]
    else:
      if not isinstance(cur, dict) or tok not in cur:
        return False
      if last:
        cur.pop(tok, None)
        return True
      cur = cur[tok]
  return False


@dataclass
class PersistVerdict:
  sections: Dict[str, Any]
  changes: List[Dict[str, Any]] = field(default_factory=list)
  refused: List[Dict[str, Any]] = field(default_factory=list)
  rewrites: List[Dict[str, Any]] = field(default_factory=list)
  asks: List[Dict[str, Any]] = field(default_factory=list)
  receipts: List[str] = field(default_factory=list)
  questions: List[str] = field(default_factory=list)
  ran_model: bool = False
  error: str = ""
  elapsed_ms: int = 0


def _fmt_money(v: Any) -> str:
  fv = _f(v)
  return "${:,.0f}".format(fv) if fv is not None else str(v)



def _field_in_her_words(key: str, row_name: str = "") -> str:
  """The name we gave a field, with the row it sits on - never the key. "" when the
  field has no name (then the question says 'here', as before)."""
  leaf = re.sub(r"\[\d+\]$", "", str(key or "").split(".")[-1])
  try:
    from client_intake_and_finmo.intake_required_fields import human_field_name  # type: ignore
    named = str(human_field_name(leaf) or "")
  except Exception:
    named = ""
  if not named or named.replace(" ", "_").lower() == leaf.lower():
    return ""
  return "%s for %s" % (named, row_name) if row_name else named


def _capacity_or_field_question(from_key: str, to_key: str, value, rewrite, row_name: str = "") -> str:
  """The question door C asks when its model says a value is on the wrong
  field. In the client's terms, naming the value and both readings - never the
  field names, which mean nothing to them.

  A READBACK NAMES WHAT IT IS ASKING ABOUT (Cowork 1231, CW-070 clone e7120169): the
  question quoted her sentence about twelve hundred jars a month and asked "Should I
  record  here" about geographic coverage - her words, exact and contiguous, as evidence
  for a question about something else. "Here" tells her nothing; the field's own name,
  on its own row, lets her see what she is being asked."""
  words = str((rewrite or {}).get("client_words") or "").strip().strip('"')
  shown = value
  try:
    if isinstance(value, float) and value == int(value):
      shown = int(value)
  except (TypeError, ValueError):
    pass
  lead = "Just so I record this the way you meant it"
  if words:
    # her words in full (2026-09-14): a cut quote read back to her is a sentence
    # she did not say, and 160 characters ends before the ceiling and the reason
    lead += ' - you said "%s"' % words
  if from_key != to_key:
    return ("%s. Is %s the most you can have on the go at any one time, or the "
            "number you get through in a period? I want to put it in the right "
            "place rather than guess." % (lead, shown))
  _named = _field_in_her_words(from_key, row_name)
  if _named:
    return ("%s. Should I record %s as %s, or have I put it in the wrong place?" % (lead, shown, _named))
  return ("%s. Should I record %s here, or have I put it in the wrong place?" % (lead, shown))


def review(*, pre: Dict[str, Any], post: Dict[str, Any], user_text: str, messages: List[Dict[str, Any]],
           stage: str, allowed_patch: Optional[Dict[str, Any]] = None, guard_rewrites: Optional[List[str]] = None,
           post_fn=None) -> PersistVerdict:
  """pre/post: {"ops":..., "market":..., "people":..., "financials":...} (post
  values None when the section was not written). Returns the sections to
  persist (possibly corrected) and everything it saw."""
  t0 = time.monotonic()
  sections = {k: (copy.deepcopy(v) if v is not None else None) for k, v in post.items()}
  verdict = PersistVerdict(sections=sections)
  if not enabled():
    return verdict
  try:
    changes = diff_sections(pre, post)
    lever_delta = lever_writes_delta(pre.get("financials") or {}, post.get("financials") or {})
    classified = classify(changes, allowed_patch=dict(allowed_patch or {}), lever_delta=lever_delta,
                          guard_rewrites=list(guard_rewrites or []), user_text=user_text)
    classified = mark_cadence_defaults(classified, post)
    verdict.changes = classified

    # 2. A COST OPTION NEVER TOUCHES STATED REVENUE.
    rev_change = next((c for c in classified if c["path"] == "financials.current_revenue"), None)
    if rev_change is not None and rev_change.get("origin") == _prov.OPTION_PICK:
      cost_keys = [k for k in lever_delta if k in COST_LEVER_FIELDS]
      ops_keys = [k for k in lever_delta if str(k).startswith("ops:")]
      if cost_keys and not ops_keys and sections.get("financials") is not None and rev_change.get("from") is not None:
        fin = sections["financials"]
        fin["current_revenue"] = rev_change["from"]
        coh = fin.get("_coherence") if isinstance(fin.get("_coherence"), dict) else None
        if coh and isinstance(coh.get("_lever_writes"), dict):
          coh["_lever_writes"].pop("current_revenue", None)
        rev_change["verdict"] = "refused"
        verdict.refused.append({"path": "financials.current_revenue", "from": rev_change["to"], "to": rev_change["from"],
                                "why": "a cost option's side effect may never rewrite the client's stated revenue"})
        verdict.receipts.append(
          f"Your revenue stays at {_fmt_money(rev_change['from'])} a year, exactly as you told me - a cost "
          "choice never rewrites it.")

    # 5. STATED-FACT LEAVES NO DOOR HAS SEEN -> door A's model, against the client's words.
    unreviewed = [c for c in classified if c.get("verdict") == "unreviewed" and c.get("to") is not None]
    if unreviewed:
      from client_intake_and_finmo.intake_guard import door_a as _door_a
      patch = {c["path"]: c["to"] for c in unreviewed}
      store = {"ops": pre.get("ops") or {}, "market": pre.get("market") or {}, "people": pre.get("people") or {},
               "financials": pre.get("financials") or {}}
      v = _door_a.review(patch=patch, user_text=str(user_text or ""), messages=list(messages or []), store=store,
                         focus=f"persist:{stage}", hold=None, post=post_fn)
      verdict.ran_model = bool(v.ran)
      verdict.error = v.error or ""
      # ONE QUESTION PER THING SHE SAID (CW-070 turn 5, draft 71d4e505): her one sentence
      # "please treat the whole thing as monthly" wrote the same 12 to two products, and
      # the question was asked once per WRITE - word for word, twice in one message. Holds
      # stay per field; the question is asked once per (her words, value, field), naming
      # every row it covers.
      _q_groups: Dict[tuple, Dict[str, Any]] = {}
      for r in v.rewrites or []:
        fk, tk, val = str(r.get("from_key") or ""), str(r.get("to_key") or r.get("from_key") or ""), r.get("value")
        sec_from, _, rest_from = fk.partition(".")
        sec_to, _, rest_to = tk.partition(".")
        c = next((x for x in unreviewed if x["path"] == fk), None)
        if c is None or sections.get(sec_from) is None:
          continue
        # AN OPINION THAT IDENTIFIES A WRONG VALUE HOLDS THE TURN (Nick
        # 2026-09-13, Alderman & Fitch a88dae18): "A guard that watches a bad
        # value land and files a note about it is not a guard. It's a witness.
        # Change it, or hold the turn and ask. Those are the only two
        # outcomes."
        #
        # It asks rather than rewrites, and the earlier ruling is why.
        # NO REWRITE AT THE PERSIST DOOR (third proof run, 2026-09-12): with
        # the question out of view the model moved a principal answer onto
        # interest and an annual overhead onto its monthly figure - the router
        # had been right, and a blind correction here made it wrong.
        # Corrections with authority need the question in view.
        #
        # An ASK is what puts it back in view. So the model's rewrite becomes
        # a question naming the value and both candidate fields, the pre-turn
        # value is restored while it is outstanding, and the client settles it
        # in one line. `model_opinion` as a category that records and does
        # nothing is gone: on Alderman & Fitch it diagnosed four hulls a week
        # correctly and the number landed anyway.
        if sections.get(sec_to) is None and tk != fk:
          c["verdict"] = "reviewed_allowed"
          c["model_note"] = "rewrite target section not present: " + tk
          continue
        # A READBACK THAT DOES NOT NAME ITS FIGURE IS NEVER SENT (Cowork 1228, CW-070
        # clone e7120169): "Should I record  here" - an empty value quoted back as the
        # thing to confirm. She cannot confirm or refuse a number she is not shown, so a
        # rewrite with no value to name holds nothing and asks nothing.
        if val is None or (isinstance(val, str) and not val.strip()):
          c["model_note"] = "no value to name - not asked"
          continue
        _set_path(sections[sec_from], rest_from, c.get("from"))      # held back until answered
        c["verdict"] = "asked"
        _row_name = ""
        if "products[" in rest_from:
          _row_name = str(_get_path(sections.get(sec_from) or {}, rest_from.rsplit(".", 1)[0] + ".product_name") or "")
        _ask = {"key": fk, "question": "", "client_words": r.get("client_words"), "why": r.get("why"), "from": c.get("to")}
        verdict.asks.append(_ask)
        _gkey = (str(r.get("client_words") or "").strip(), str(val), _leaf_name(fk), _leaf_name(tk))
        _grp = _q_groups.setdefault(_gkey, {"fk": fk, "tk": tk, "val": val, "r": r, "rows": [], "asks": []})
        if _row_name and _row_name not in _grp["rows"]:
          _grp["rows"].append(_row_name)
        _grp["asks"].append(_ask)
        continue
      for _grp in _q_groups.values():
        _rows = _grp["rows"]
        _rows_text = (_rows[0] if len(_rows) == 1 else ", ".join(_rows[:-1]) + " and " + _rows[-1]) if _rows else ""
        _question = _capacity_or_field_question(_grp["fk"], _grp["tk"], _grp["val"], _grp["r"], row_name=_rows_text)
        for _ask in _grp["asks"]:
          _ask["question"] = _question
        verdict.questions.append(_question)
      for a in v.asks or []:
        fk = str(a.get("key") or "")
        sec, _, rest = fk.partition(".")
        c = next((x for x in unreviewed if x["path"] == fk), None)
        if c is not None and sections.get(sec) is not None:
          _set_path(sections[sec], rest, c.get("from"))                # held back until answered
          c["verdict"] = "asked"
          verdict.asks.append({"key": fk, "question": a.get("question"), "client_words": a.get("client_words"),
                               "why": a.get("why"), "from": c.get("to")})
          if a.get("question"):
            verdict.questions.append(str(a["question"]))
      for c in unreviewed:
        if c.get("verdict") == "unreviewed":
          c["verdict"] = "reviewed_allowed" if v.ran and not v.error else "unguarded"
  except Exception as exc:  # noqa: BLE001 - FAIL OPEN, LOUDLY
    logger.error("INTAKE_GUARD_C_FAILED stage=%s - the turn persists unguarded: %s: %s", stage, type(exc).__name__, exc)
    verdict.error = f"{type(exc).__name__}: {exc}"[:300]
    verdict.sections = {k: (copy.deepcopy(v) if v is not None else None) for k, v in post.items()}
  verdict.elapsed_ms = int((time.monotonic() - t0) * 1000)
  return verdict


def summary(verdict: PersistVerdict) -> Dict[str, Any]:
  origins: Dict[str, int] = {}
  verdicts: Dict[str, int] = {}
  for c in verdict.changes:
    origins[c.get("origin") or "none"] = origins.get(c.get("origin") or "none", 0) + 1
    verdicts[c.get("verdict") or "?"] = verdicts.get(c.get("verdict") or "?", 0) + 1
  return {"changed": len(verdict.changes), "origins": origins, "verdicts": verdicts, "refused": len(verdict.refused),
          "rewrote": sum(1 for r in verdict.rewrites if r.get("applied", True)),
          # no "opinions" key: an opinion that identifies a wrong value now
          # holds the turn as an ask (Nick 2026-09-13). Nothing is recorded
          # and left to land.
          "asked": len(verdict.asks), "ran_model": verdict.ran_model,
          "error": verdict.error or None}


def record(conn, *, draft_id: str, turn: int, stage: str, verdict: PersistVerdict) -> None:
  """ONE ROW PER PERSISTED TURN, changed or not - the proof table."""
  from client_intake_and_finmo.intake_guard import audit as _audit
  s = summary(verdict)
  seen = [{"path": c["path"], "from": c.get("from"), "to": c.get("to"), "origin": c.get("origin"), "verdict": c.get("verdict")}
          for c in verdict.changes]
  why = "ran_model" if verdict.ran_model else "no_model_needed"
  if verdict.error:
    why = "unguarded:" + verdict.error[:120]
  if s["refused"]:
    why += f"; refused {s['refused']}"
  if s["rewrote"]:
    why += f"; rewrote {s['rewrote']}"
  if s["asked"]:
    why += f"; asked {s['asked']}"
  # the audit JSON-encodes values itself; hand it objects, never a string
  _audit.record(conn, draft_id=str(draft_id), turn=int(turn), door="C", action="turn_review", field=f"stage:{stage}",
                from_value=seen[:400], to_value=s,
                receipt=" ".join(verdict.receipts)[:2000], why=why, elapsed_ms=verdict.elapsed_ms or None)
  for r in verdict.refused:
    _audit.record(conn, draft_id=str(draft_id), turn=int(turn), door="C", action="refused_write", field=r["path"],
                  from_value=r.get("from"), to_value=r.get("to"), why=r.get("why") or "", elapsed_ms=None)
  for r in verdict.rewrites:
    _audit.record(conn, draft_id=str(draft_id), turn=int(turn), door="C",
                  action="rewrote_write",
                  field=f"{r.get('from_key')} -> {r.get('to_key')}", to_value=r.get("value"),
                  client_words=str(r.get("client_words") or ""), receipt=str(r.get("receipt") or ""),
                  why=str(r.get("why") or ""), elapsed_ms=None)
  for a in verdict.asks:
    _audit.record(conn, draft_id=str(draft_id), turn=int(turn), door="C", action="asked", field=a.get("key"),
                  from_value=a.get("from"), client_words=str(a.get("client_words") or ""),
                  receipt=str(a.get("question") or ""), why=str(a.get("why") or ""), elapsed_ms=None)
