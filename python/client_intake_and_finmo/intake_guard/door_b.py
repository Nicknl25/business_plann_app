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


def explained_figures(store: Dict[str, Any], lever_writes: Optional[Dict[str, Any]] = None, user_text: str = "",
                      reply_text: str = "", recent_user_texts: Optional[List[str]] = None) -> List[float]:
  """Every figure the reply is entitled to say: the store in any common
  basis, the walk's record, the option prices, the gap arithmetic, the
  client's words (this turn and the last few), and the app's own arithmetic
  on stored figures - a percentage the reply names applied to a stored
  figure, and the sum of two stored financial figures."""
  vals: List[float] = list(_store_leaves(store).values())
  fin_top = [v for k, v in _store_leaves(store).items() if k.startswith("financials.") and k.count(".") == 1 and v > 0]
  fin_top = sorted(set(round(x, 2) for x in fin_top))[:40]
  for i in range(len(fin_top)):
    for j in range(i, len(fin_top)):
      vals.append(fin_top[i] + fin_top[j])
  for m in _PCT_RE.finditer(str(reply_text or "")):
    try:
      pct = float(m.group(1)) / 100.0
    except ValueError:
      continue
    for base in fin_top:
      vals.append(base * pct)
  try:
    from client_intake_and_finmo.intake_guard.door_c import numbers_in_words
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
    from client_intake_and_finmo.intake_guard.door_c import numbers_in_words
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
  out = []
  for m in _DOLLAR_RE.finditer(str(text or "")):
    try:
      v = float(m.group(1).replace(",", ""))
    except ValueError:
      continue
    mult = (m.group(2) or "").lower()
    if mult in ("k", "thousand"):
      v *= 1000.0
    elif mult in ("m", "million"):
      v *= 1_000_000.0
    if v < 100:
      continue
    s = max(0, m.start() - 90)
    out.append({"value": v, "sentence": str(text or "")[s:m.end() + 40].replace("\n", " ")})
  return out


def find_disagreements(text: str, store: Dict[str, Any], lever_writes: Optional[Dict[str, Any]] = None,
                       user_text: str = "", recent_user_texts: Optional[List[str]] = None) -> List[Dict[str, Any]]:
  """Deterministic, on EVERY figure: a dollar figure the reply states that
  nothing entitles it to say; and the literal 'nothing moved' against a
  non-empty lever-writes record (one cheap signal kept, not the gate)."""
  out: List[Dict[str, Any]] = []
  vals = explained_figures(store, lever_writes, user_text, reply_text=text, recent_user_texts=recent_user_texts)
  for fig in _dollar_figures(text):
    v = fig["value"]
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
  "the contradiction cannot be fixed from the store, keep the reply and set changed=false."
)


def _post_rewrite(text: str, disagreements: List[Dict[str, Any]], store: Dict[str, Any],
                  lever_writes: Optional[Dict[str, Any]], post) -> ReplyVerdict:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    logger.error("INTAKE_GUARD_B_NO_KEY - reply sent unguarded")
    return ReplyVerdict(text=text, disagreements=disagreements, error="no_api_key")
  fin = {k: v for k, v in ((store.get("financials") or {}).items()) if not str(k).startswith("_")}
  body = {"reply": text, "disagreements": disagreements, "store_financials": fin,
          "lever_writes": lever_writes or {}, "ops_lines": (store.get("ops") or {}).get("lob_models")}
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
    walk_turn = any(isinstance(w, dict) and w.get("to") is not None for w in (lever_writes or {}).values())
    if dis or walk_turn:
      if post is None:
        from client_intake_and_finmo.openai_http import post_openai_with_retries as post  # type: ignore
      verdict = _post_rewrite(base, dis, store, lever_writes, post)
      verdict.figures_found = len(_dollar_figures(base))
      verdict.compared_walk = walk_turn
  # the panel renders text raw: markdown emphasis from the naturaliser would
  # reach the client as asterisks (guarded run 2, turn 52: "**$11,313**")
  verdict.text = strip_markdown_emphasis(verdict.text)
  extras: List[str] = []
  for r in receipts or []:
    if r and r not in verdict.text:
      extras.append(r)
  for q in questions or []:
    if q and q not in verdict.text:
      extras.append(q)
  if extras:
    verdict.text = (verdict.text.rstrip() + "\n\n" + " ".join(extras)).strip()
    verdict.appended = extras
  return verdict
