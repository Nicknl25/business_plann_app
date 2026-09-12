"""DOOR B - the reply, before it goes out.

Every figure the reply states is checked against the store as it stands
after the turn's writes (deterministic). A reply that contradicts the
store - a receipt naming a figure the store does not hold, or "nothing
moved" while the walk's lever writes say six fields moved - is rewritten
from the store by the model, in the client's language, or held. The
guard's own door-A receipts and questions are appended here, so the reply
that persists is the reply that is sent.

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

_CLAIM_RE = re.compile(
  r"(?i)(?:recorded|i'?ll use|i will use|i'?ve (?:set|put|recorded|left)|set (?:it )?to|now (?:at|reads)|"
  r"moved|comes to|is now|stays at|to \$)[^.\n]{0,80}?\$\s?(\d[\d,]*\.?\d*)"
)
_NOTHING_MOVED_RE = re.compile(r"(?i)nothing (?:you told me )?(?:was )?moved by the levers")


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


def _store_leaves(store: Dict[str, Any]) -> Dict[str, float]:
  return numeric_leaves({k: v for k, v in (store or {}).items() if k in ("financials", "ops", "people")})


def find_disagreements(text: str, store: Dict[str, Any], lever_writes: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  """Deterministic: a figure the reply CLAIMS is recorded/set/used that the
  store does not hold in any common basis; and the 'nothing moved' claim
  against a non-empty lever-writes record."""
  out: List[Dict[str, Any]] = []
  leaves = _store_leaves(store)
  vals = list(leaves.values())
  # PROVENANCE: a receipt that reads "X to Y" names the old value on purpose;
  # every 'from' of the walk's lever writes is an authorised figure (the
  # option pick moved it), never a claim the store must still hold
  for w in (lever_writes or {}).values():
    if isinstance(w, dict) and w.get("from") is not None:
      try:
        vals.append(float(w["from"]))
      except (TypeError, ValueError):
        pass
  for m in _CLAIM_RE.finditer(text or ""):
    try:
      v = float(m.group(1).replace(",", ""))
    except ValueError:
      continue
    if v < 100:
      continue
    if any(_close(s, e) for s in vals for e in _equivalents(v)):
      continue
    # "$A to $B": A is where it was; only B is the claim
    tail = (text or "")[m.end():m.end() + 24]
    if re.match(r"\s*(to|->)\s*\$", tail):
      continue
    out.append({"kind": "claimed_figure_not_in_store", "value": v, "sentence": m.group(0)[:160]})
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
  "You check the consultant's reply to a small-business owner against the store of what the owner has told us, "
  "before the reply is sent. The reply states one or more figures the store does not hold (listed as "
  "`disagreements`), or claims nothing moved when the store's lever writes say figures moved. Rewrite ONLY the "
  "sentences that contradict the store so they state what the store holds, in the owner's own language, and "
  "keep every other sentence exactly as it is. Never introduce a figure that is not in the store or the owner's "
  "words. If the contradiction cannot be fixed from the store, keep the reply and set changed=false."
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
  # the rewrite may not introduce a figure the store does not hold
  leaves = list(_store_leaves(store).values())
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
           receipts: Optional[List[str]] = None, questions: Optional[List[str]] = None, post=None) -> ReplyVerdict:
  """The door. Deterministic check first; the model only on a disagreement.
  Door A's receipts and questions are appended so they reach the client."""
  base = str(text or "")
  verdict = ReplyVerdict(text=base)
  if enabled() and base.strip():
    dis = find_disagreements(base, store, lever_writes)
    if dis:
      if post is None:
        from client_intake_and_finmo.openai_http import post_openai_with_retries as post  # type: ignore
      verdict = _post_rewrite(base, dis, store, lever_writes, post)
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
