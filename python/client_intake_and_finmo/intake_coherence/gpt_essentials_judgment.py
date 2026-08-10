"""THE ESSENTIALS JUDGE (CW-024 slate item 8 supersede, Nick-ruled).

The costs round offers cuts to composite expense lines (other operating
costs, direct costs). What is INSIDE those lines differs per business -
a grounds crew's "other operating costs" carries fleet insurance and
fuel; a donut shop's carries health permits and utilities. The old
CW-022 #5 doctrine asked the client ("tell me what's in those lines
first") on every deep cut. The ruled supersede: the app REASONS about
this business's expense composition itself and offers only the
discretionary slice; the ask-first wording remains ONLY where the judge
genuinely cannot tell.

THE FENCE (same as the demand judge):
  1. NO HARDCODED ESSENTIALS LIST, ever. A fixed "insurance = essential,
     marketing = discretionary" table does not know the business - the
     judge reasons from what THIS business is (type, description, ops
     model, what already lives in other lines).
  2. BANDS, NEVER POINTS: the essential fraction of a line is a RANGE at
     least 10 points wide; the walk consumes the CONSERVATIVE (high)
     edge - when unsure, protect MORE of the line, cut less.
  3. VIABILITY-BLIND: the judge never sees the plan's gap or verdicts.
  4. THIN-EVIDENCE DOCTRINE, enforced in the VALIDATOR: evidence is
     classified in PYTHON; thin -> every verdict WITHHELD and the costs
     round keeps the ask-first wording (absence of judgment is never a
     verdict).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

# The composite lines the costs round can cut into. Marketing carries
# its own demand-coupled consequence (the demand judge); rent has the
# lease gate; payroll has the cause-split - none of them belong here.
_JUDGED_LINES = ("gna", "cogs")

# Anti-false-precision floor: no band may claim to know a line's
# essential share tighter than 10 percentage points.
_MIN_BAND_WIDTH = 0.10


def essentials_evidence_level(
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """PYTHON-side evidence classification (never GPT-claimed). RICH only
  when the app genuinely knows what this business IS - a business type
  plus either a real description or an ops model to reason from. Line
  amounts are checked per line at consumption; this gate is about
  whether composition reasoning is possible at all."""
  ops = ops_json if isinstance(ops_json, dict) else {}
  reasons = []
  if not str(ops.get("business_type") or "").strip():
    reasons.append("no_business_type")
  has_description = bool(str(ops.get("business_description_summary") or "").strip())
  has_model = bool(ops.get("lob_models"))
  if not (has_description or has_model):
    reasons.append("no_description_or_operating_model")
  return {"level": "thin" if reasons else "rich", "reasons": reasons}


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_essentials_judgment",
    "description": "Submit the expense-composition judgment. Call exactly once.",
    "parameters": {
      "type": "object",
      "properties": {
        "gna": {
          "type": "object",
          "description": (
            "The 'other operating costs' line: everything this business "
            "pays to exist that is NOT payroll, rent, marketing, or "
            "direct fulfillment cost. Reason about what THIS business's "
            "line most plausibly contains and how much of it the "
            "business cannot drop and keep operating as described."
          ),
          "properties": {
            "essential_fraction_band": {
              "type": "array", "items": {"type": "number"},
              "minItems": 2, "maxItems": 2,
              "description": (
                "The plausible RANGE of the CURRENT line that is "
                "essential - costs that cannot be dropped while the "
                "business keeps operating as described (fractions, e.g. "
                "[0.55, 0.75]). At least 10 points wide - narrower "
                "claims false precision."
              ),
            },
            "named_essentials": {
              "type": "string",
              "description": (
                "Plain client-facing words naming the essential costs "
                "you reasoned are inside (e.g. 'insurance, fuel, and "
                "licensing'). Everyday language only - no internal "
                "vocabulary, no field names."
              ),
            },
            "basis": {"type": "string"},
          },
          "required": ["essential_fraction_band", "named_essentials", "basis"],
        },
        "cogs": {
          "type": "object",
          "description": (
            "The direct-cost line (materials, supplies, direct non-labor "
            "fulfillment). How much of the CURRENT spend is the floor "
            "for delivering the work the business already books - versus "
            "waste, over-buying, or premium substitutions it could "
            "realistically trim?"
          ),
          "properties": {
            "essential_fraction_band": {
              "type": "array", "items": {"type": "number"},
              "minItems": 2, "maxItems": 2,
            },
            "named_essentials": {"type": "string"},
            "basis": {"type": "string"},
          },
          "required": ["essential_fraction_band", "named_essentials", "basis"],
        },
        "rationale": {"type": "string"},
      },
      "required": ["gna", "cogs", "rationale"],
    },
  },
}

_SYSTEM_PROMPT = (
  "You are the EXPENSE-COMPOSITION JUDGE for one specific business. Two "
  "of its expense lines are composites the client stated as single "
  "numbers: 'other operating costs' and 'direct costs'. From what this "
  "business IS - its type, its own description, how it delivers work, "
  "what already lives in its other lines (payroll, rent, and marketing "
  "are separate and are NOT in these lines) - judge how much of each "
  "line is ESSENTIAL: costs the business cannot drop while continuing "
  "to operate as described.\n"
  "RULES:\n"
  "1. JUDGE THE BUSINESS, NOT A CATEGORY LIST. Never apply a fixed "
  "'insurance is essential, software is optional' table - the same cost "
  "is essential in one business and discretionary in another. Reason "
  "from the operation described.\n"
  "2. BANDS, NEVER POINTS: every fraction is a RANGE at least 10 points "
  "wide. The range plus the reasoning IS the judgment.\n"
  "3. You are VIABILITY-BLIND: you know nothing about any plan or gap "
  "and must not try to help or hurt one. Judge composition as it is.\n"
  "4. named_essentials is read by the client: everyday words for the "
  "specific costs you reasoned are in there, nothing internal.\n"
  "5. Your basis strings must cite the EVIDENCE (what the business does, "
  "how it fulfills, what its scale implies), not restate the verdict.\n"
  "Call submit_essentials_judgment exactly once."
)


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


def gpt_author_essentials_once(
  *,
  compact: Dict[str, Any],
  cost_lines: Dict[str, Any],
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """ONE composition call; returns {ok, judgment, error}. RAW - callers
  must pass the result through validate_essentials."""
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
    "BUSINESS COMPACT (what this business IS):\n"
    + json.dumps(compact or {}, ensure_ascii=False, default=str)
    + "\n\nTHE COMPOSITE LINES (annual dollars as stated; payroll, rent "
    "and marketing live in their own lines and are NOT inside these):\n"
    + json.dumps(cost_lines or {}, ensure_ascii=False, default=str)
  )
  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function",
                    "function": {"name": "submit_essentials_judgment"}},
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


def _rail_band(raw: Any) -> Optional[list]:
  """Clamp to [0,1], order, and enforce the minimum width by widening
  UPWARD around the lower value - the conservative direction for a CUT:
  a too-narrow band gets a HIGHER protected share (cut less), never a
  deeper offerable cut."""
  if not isinstance(raw, (list, tuple)) or len(raw) != 2:
    return None
  try:
    lo, hi = float(raw[0]), float(raw[1])
  except (TypeError, ValueError):
    return None
  lo, hi = max(0.0, min(1.0, min(lo, hi))), max(0.0, min(1.0, max(lo, hi)))
  if hi - lo < _MIN_BAND_WIDTH:
    hi = min(1.0, lo + _MIN_BAND_WIDTH)
  return [round(lo, 4), round(hi, 4)]


def validate_essentials(
  *,
  judgment: Dict[str, Any],
  evidence: Dict[str, Any],
) -> Dict[str, Any]:
  """Rail the raw judgment. THE THIN-EVIDENCE RULE IS ENFORCED HERE:
  thin evidence -> every line verdict WITHHELD, whatever GPT said - the
  costs round then keeps the ask-first wording. Rich evidence -> bands
  clamped, ordered, floored at the 10-point width (widened UPWARD, the
  conservative direction for cuts)."""
  j = judgment or {}
  level = str((evidence or {}).get("level") or "thin")
  notes = []
  out: Dict[str, Any] = {
    "evidence_level": level,
    "evidence_reasons": list((evidence or {}).get("reasons") or []),
    "rationale": str(j.get("rationale") or "")[:800],
  }
  if level != "rich":
    out.update({"lines": {}, "withheld": True})
    notes.append("verdicts_withheld_thin_evidence")
    out["notes"] = notes
    return out

  lines: Dict[str, Any] = {}
  for key in _JUDGED_LINES:
    raw = j.get(key) or {}
    band = _rail_band(raw.get("essential_fraction_band"))
    named = str(raw.get("named_essentials") or "").strip()
    if band and named:
      lines[key] = {
        "essential_fraction_band": band,
        "named_essentials": named[:200],
        "basis": str(raw.get("basis") or "")[:500],
      }
    else:
      notes.append(f"{key}_invalid_dropped")
  out["lines"] = lines
  out["withheld"] = False
  out["notes"] = notes
  return out
