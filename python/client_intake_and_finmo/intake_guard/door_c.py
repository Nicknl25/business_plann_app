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

WHAT IT DOES with each changed leaf, in order:
  1. origin_of (provenance.py, now wired): router_patch (door A allowed it
     this turn), option_pick (the walk's lever-writes record), guard_rewrite,
     estimator_baseline -> authorised, recorded.
  2. a COST option may never touch stated revenue (Nick: "$4,600,000 became
     $3,449,999.99 from a marketing decision"): a current_revenue change in a
     turn whose lever writes are cost fields and no price/volume move is
     REFUSED - the pre-turn value is restored, the lever write removed, and
     the client reads a receipt.
  3. the number the client just said, in any common basis -> client_words,
     recorded, no model call (that is most of the financials stage).
  4. a twin of an explained number (x12, /12, x4, /4) -> twin, recorded.
  5. a STATED-FACT field with none of the above -> unreviewed: door A's model
     reviews it against the client's words (rewrite / ask / allow), exactly as
     it would a router patch. An ask restores the pre-turn value and holds.
  6. anything else (summaries, bookkeeping, derived model fields) -> recorded
     as derived; never a model call, never a hold.
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
    origin = _prov.origin_of(path, allowed_patch=allowed_patch, lever_writes=lever_delta, guard_rewrites=guard_rewrites)
    stated = _prov.is_stated_fact(path)
    if origin is None and _ROSTER_RE.match(path):
      # the roster is the people door's (door A on the router path reviews it
      # row by row); a persist-time model moving values between rows lost a
      # named wage on the first proof run. Recorded, never reviewed here.
      origin = "roster"
    if origin is None and _ROSTER_RE.match(path):
      # the roster is the people door's (door A on the router path reviews it
      # row by row); a persist-time model moving values between rows lost a
      # named wage on the first proof run. Recorded, never reviewed here.
      origin = "roster"
    if origin is None and _f(c.get("to")) is not None and any(_close(e, n) for n in explained_numbers if n not in words for e in _equiv(_f(c["to"]))):
      origin = "twin"   # arithmetic on a figure a door or the walk authorised this turn
    if origin is None and not stated:
      origin = "client_words" if _in_words(c.get("to"), words) else "derived"
    out.append({**c, "leaf": leaf, "origin": origin, "stated_fact": stated})
  # A STATED FACT IS REVIEWED BY THE MODEL EVEN WHEN THE NUMBER IS IN THE
  # CLIENT'S WORDS - the van lease was "2,400 a month" in their words and it
  # landed on rent. Only its monthly/annual twin in the same turn is spared:
  # the base leaf (the figure as the client said it) carries the review.
  pending = [c for c in out if c["origin"] is None]
  for c in pending:
    fv = _f(c.get("to"))
    if fv is None:
      c["origin"] = "unreviewed"
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
    c["origin"] = "twin" if base is not None else "unreviewed"
  return out


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
        rev_change["origin"] = "refused_cost_lever_touched_revenue"
        verdict.refused.append({"path": "financials.current_revenue", "from": rev_change["to"], "to": rev_change["from"],
                                "why": "a cost option's side effect may never rewrite the client's stated revenue"})
        verdict.receipts.append(
          f"Your revenue stays at {_fmt_money(rev_change['from'])} a year, exactly as you told me - a cost "
          "choice never rewrites it.")

    # 5. STATED-FACT LEAVES NO DOOR HAS SEEN -> door A's model, against the client's words.
    unreviewed = [c for c in classified if c.get("origin") == "unreviewed" and c.get("to") is not None]
    if unreviewed:
      from client_intake_and_finmo.intake_guard import door_a as _door_a
      patch = {c["path"]: c["to"] for c in unreviewed}
      store = {"ops": pre.get("ops") or {}, "market": pre.get("market") or {}, "people": pre.get("people") or {},
               "financials": pre.get("financials") or {}}
      v = _door_a.review(patch=patch, user_text=str(user_text or ""), messages=list(messages or []), store=store,
                         focus=f"persist:{stage}", hold=None, post=post_fn)
      verdict.ran_model = bool(v.ran)
      verdict.error = v.error or ""
      for r in v.rewrites or []:
        fk, tk, val = str(r.get("from_key") or ""), str(r.get("to_key") or r.get("from_key") or ""), r.get("value")
        sec_from, _, rest_from = fk.partition(".")
        sec_to, _, rest_to = tk.partition(".")
        c = next((x for x in unreviewed if x["path"] == fk), None)
        if c is None or sections.get(sec_from) is None:
          continue
        # NO REWRITE AT THE PERSIST DOOR (third proof run, 2026-09-12): with
        # the question out of view the model moved a principal answer onto
        # interest and an annual overhead onto its monthly figure - the
        # router had been right. Corrections with authority live at door A,
        # on the router paths, with the question in view. Here the model's
        # rewrite is recorded as its opinion; only an ASK changes anything.
        if True:
          c["origin"] = "allowed_by_model"
          c["model_note"] = ("would rewrite %s -> %s = %r: %s" % (fk, tk, val, str(r.get("why") or "")[:240]))
          verdict.rewrites.append({"from_key": fk, "to_key": tk, "value": val, "client_words": r.get("client_words"),
                                   "receipt": r.get("receipt"), "why": r.get("why"), "applied": False})
          continue
        if tk != fk and val is not None and not _set_path(sections[sec_to], rest_to, val):
          c["origin"] = "allowed_by_model"
          c["model_note"] = "rewrite target not resolvable: " + tk
          continue
        if c.get("from") is None:
          _del_path(sections[sec_from], rest_from)                 # an added value comes off
        else:
          _set_path(sections[sec_from], rest_from, c.get("from"))  # a moved value is restored
        if tk == fk and val is not None:
          _set_path(sections[sec_from], rest_from, val)            # restored to what the client said
        c["origin"] = "guard_rewrite"
        verdict.rewrites.append({"from_key": fk, "to_key": tk, "value": val, "client_words": r.get("client_words"),
                                 "receipt": r.get("receipt"), "why": r.get("why")})
        if r.get("receipt"):
          verdict.receipts.append(str(r["receipt"]))
      for a in v.asks or []:
        fk = str(a.get("key") or "")
        sec, _, rest = fk.partition(".")
        c = next((x for x in unreviewed if x["path"] == fk), None)
        if c is not None and sections.get(sec) is not None:
          _set_path(sections[sec], rest, c.get("from"))                # held back until answered
          c["origin"] = "asked"
          verdict.asks.append({"key": fk, "question": a.get("question"), "client_words": a.get("client_words"),
                               "why": a.get("why"), "from": c.get("to")})
          if a.get("question"):
            verdict.questions.append(str(a["question"]))
      for c in unreviewed:
        if c.get("origin") == "unreviewed":
          c["origin"] = "allowed_by_model" if v.ran and not v.error else "unguarded"
  except Exception as exc:  # noqa: BLE001 - FAIL OPEN, LOUDLY
    logger.error("INTAKE_GUARD_C_FAILED stage=%s - the turn persists unguarded: %s: %s", stage, type(exc).__name__, exc)
    verdict.error = f"{type(exc).__name__}: {exc}"[:300]
    verdict.sections = {k: (copy.deepcopy(v) if v is not None else None) for k, v in post.items()}
  verdict.elapsed_ms = int((time.monotonic() - t0) * 1000)
  return verdict


def summary(verdict: PersistVerdict) -> Dict[str, Any]:
  origins: Dict[str, int] = {}
  for c in verdict.changes:
    origins[c.get("origin") or "?"] = origins.get(c.get("origin") or "?", 0) + 1
  return {"changed": len(verdict.changes), "origins": origins, "refused": len(verdict.refused),
          "rewrote": sum(1 for r in verdict.rewrites if r.get("applied", True)),
          "opinions": sum(1 for r in verdict.rewrites if not r.get("applied", True)),
          "asked": len(verdict.asks), "ran_model": verdict.ran_model,
          "error": verdict.error or None}


def record(conn, *, draft_id: str, turn: int, stage: str, verdict: PersistVerdict) -> None:
  """ONE ROW PER PERSISTED TURN, changed or not - the proof table."""
  from client_intake_and_finmo.intake_guard import audit as _audit
  s = summary(verdict)
  seen = [{"path": c["path"], "from": c.get("from"), "to": c.get("to"), "origin": c.get("origin")} for c in verdict.changes]
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
                  action="rewrote_write" if r.get("applied", True) else "model_opinion",
                  field=f"{r.get('from_key')} -> {r.get('to_key')}", to_value=r.get("value"),
                  client_words=str(r.get("client_words") or ""), receipt=str(r.get("receipt") or ""),
                  why=str(r.get("why") or ""), elapsed_ms=None)
  for a in verdict.asks:
    _audit.record(conn, draft_id=str(draft_id), turn=int(turn), door="C", action="asked", field=a.get("key"),
                  from_value=a.get("from"), client_words=str(a.get("client_words") or ""),
                  receipt=str(a.get("question") or ""), why=str(a.get("why") or ""), elapsed_ms=None)
