"""A RECEIPT SAYS WHAT THE STORE KEPT AFTER THE GUARDS RUN, OR SAYS NOTHING ABOUT A
HELD FIELD (Nick 2026-09-14, ruling 2, answer 1).

CW-070 turn 5 (draft 71d4e505): her "treat the whole thing as monthly" wrote 12 to
two product rows; the reply said "(Noted: ... -> 12.)"; door C then held 12 back and
the store kept 52. The receipt was composed from the handler's ops object BEFORE the
persist door ran - it described a write the store refused.

The receipt text and the sections persist in ONE call, and door C can consult a
model, so no preview can promise what the persist will keep. The receipt is
therefore composed INSIDE the persist, after door C returns: the handler puts a
placeholder where the receipt goes and registers what the section held before the
turn; append_messages resolves it against the section it is about to store. A field
door C held back equals its before-value, so the receipt cannot name it.
"""
from __future__ import annotations

import copy
import random
import re
import string
from typing import Any, Dict, List, Optional

# Letters only: a digit inside a reply is a figure to every reader downstream (door
# B counts them), and a placeholder is never a figure.
TOKEN_RE = re.compile(r"\[\[app-receipt:([a-z]{12})\]\]")

_FALLBACK_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _registry() -> Dict[str, Dict[str, Any]]:
  try:
    from flask import g, has_request_context  # type: ignore
    if has_request_context():
      reg = getattr(g, "_receipt_pending", None)
      if not isinstance(reg, dict):
        reg = {}
        g._receipt_pending = reg
      return reg
  except Exception:
    pass
  return _FALLBACK_REGISTRY


def placeholder(domain: str, before: Optional[Dict[str, Any]], *, with_echo: str, without_echo: str = "") -> str:
  """The spot where the receipt for `domain` goes. `with_echo` carries {echo}; it is
  used when the stored section differs from `before`, `without_echo` otherwise."""
  key = "".join(random.choice(string.ascii_lowercase) for _ in range(12))
  _registry()[key] = {"domain": str(domain), "before": copy.deepcopy(before or {}),
                      "with_echo": str(with_echo), "without_echo": str(without_echo or "")}
  return f"[[app-receipt:{key}]]"


def echo_line(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]], domain: str) -> str:
  try:
    from client_intake_and_finmo.capture_receipt import numeric_receipt, receipt_summary  # type: ignore
    return receipt_summary(numeric_receipt(before={domain: before or {}}, after={domain: after or {}}))
  except Exception:
    return ""


def resolve(text: str, stored_sections: Dict[str, Any]) -> str:
  """Every placeholder in `text` becomes the receipt of what `stored_sections` (the
  sections as they will persist, after the guards) changed. A placeholder with no
  registration, or no stored section to read, says nothing."""
  if not text or "[[app-receipt:" not in text:
    return text
  reg = _registry()

  def _one(m: "re.Match[str]") -> str:
    entry = reg.pop(m.group(1), None)
    if not entry:
      return ""
    after = stored_sections.get(entry["domain"])
    if not isinstance(after, dict):
      return entry["without_echo"]
    echo = echo_line(entry["before"], after, entry["domain"])
    return entry["with_echo"].replace("{echo}", echo) if echo else entry["without_echo"]

  out = TOKEN_RE.sub(_one, str(text))
  out = re.sub(r"\[\[app-receipt:[^\]]*\]\]", "", out)
  out = re.sub(r"\n{3,}", "\n\n", out)
  return out.strip()


def strip(text: str) -> str:
  """A reply that never reached the persist door carries no receipt at all."""
  if not text or "[[app-receipt:" not in str(text):
    return text
  return re.sub(r"\n{3,}", "\n\n", re.sub(r"\[\[app-receipt:[^\]]*\]\]", "", str(text))).strip()


def resolve_messages(new_messages: List[Dict[str, Any]], stored_sections: Dict[str, Any]) -> List[Dict[str, Any]]:
  out = []
  for m in new_messages or []:
    if isinstance(m, dict) and m.get("role") == "assistant" and "[[app-receipt:" in str(m.get("content") or ""):
      m = dict(m, content=resolve(str(m.get("content") or ""), stored_sections))
    out.append(m)
  return out
