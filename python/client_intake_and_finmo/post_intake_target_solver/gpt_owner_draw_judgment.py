"""The executive's OWNER DEFERRED-DRAW judgment (founder comp scheduling).

THE REALITY MODELED: startup founders routinely take a reduced or
deferred draw during the ramp and recover to their stated comp once the
business supports it. Forcing the stated draw from Q1 understates the
viability of exactly the founder-led businesses this system serves.

THIS IS THE HIGHEST FAKE-VIABLE-RISK LEVER IN THE SYSTEM — "zero out
owner comp" is the classic way a failing plan fakes a pass — so the
fences are built in, non-negotiable:

  FENCE 1 — VIABILITY-BLIND: this prompt NEVER sees whether any plan
    passes. It judges what a real founder in this situation would defer
    (bounded by the founder still needing to live), not what deferral
    makes Q11 positive.
  FENCE 2 — TEMPORARY WITH EXPLICIT RECOVERY: the deferral is a window
    with a mandatory ramp back to the STATED comp; the trajectory shows
    the step back up. "Owner works free forever" is rejected by rail.
  FENCE 3 — LENDER-DEFENSIBLE RAILS (Python-clamped): deferral fraction
    <= 0.75 (a founder still has living costs; never an indefinite
    zero), window <= 12 quarters (~3 years of ramp), recovery ramp
    >= 2 quarters, full stated comp restored by quarter 16 at the
    latest. The executive can only TIGHTEN within these.
  FENCE 4 — STATED FACTS: the stated draw is the fact; this lever only
    SCHEDULES its timing across the forecast (defer early, recover to
    the same stated comp). It never invents a different owner or comp.
  FENCE 5 — DETERMINISTIC: one locked call (run-once-and-lock); a
    failed call means NO deferral (the lever stays closed).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

# Lender-defensibility rails (documented margins, not tuned knobs).
MAX_DEFERRAL_FRACTION_RAIL = 0.75   # the founder still needs to live
MAX_DEFERRAL_QUARTERS_RAIL = 12     # ~3 years of ramp, no longer
MIN_RECOVERY_QUARTERS_RAIL = 2      # comp steps back, never teleports
FULL_COMP_BY_QUARTER_RAIL = 16      # stated comp restored by year 4


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_owner_draw_judgment",
    "description": "Submit the owner deferred-draw judgment. Call exactly once.",
    "parameters": {
      "type": "object",
      "properties": {
        "max_deferral_fraction": {
          "type": "number",
          "description": (
            "The largest share of the owner's STATED draw this founder could "
            "realistically defer during the ramp (0 = no deferral is "
            "realistic; 0.5 = could live on half the stated draw for a "
            "while). Judge from the business's scale, the stated draw's "
            "size, and what founders of businesses like this actually do — "
            "a founder must still cover living costs."
          ),
        },
        "deferral_quarters": {
          "type": "integer",
          "description": (
            "How many quarters the deferral window realistically lasts "
            "before comp must start recovering (a founder tolerates a lean "
            "year or two, not forever)."
          ),
        },
        "recovery_quarters": {
          "type": "integer",
          "description": (
            "Over how many quarters comp ramps back from the deferred level "
            "to the FULL stated draw (the recovery must be visible in the "
            "trajectory)."
          ),
        },
        "rationale": {
          "type": "string",
          "description": (
            "The defense of this deferral schedule to a lender: why this "
            "founder, in this business, would realistically run this "
            "schedule (2-3 sentences)."
          ),
        },
      },
      "required": ["max_deferral_fraction", "deferral_quarters", "recovery_quarters", "rationale"],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the executive judging a FOUNDER'S DEFERRED-DRAW schedule for a "
  "business plan: how much of their STATED owner draw would this founder "
  "realistically defer during the ramp, for how long, and how fast does "
  "comp recover to the stated level.\n"
  "THE REALITY: startup founders routinely take reduced draws early and "
  "recover to market comp once the business supports it — lenders see this "
  "as founder discipline WHEN it is bounded and temporary. An owner working "
  "free forever is a red flag, not a plan.\n"
  "JUDGE FROM THE FOUNDER'S REALITY, never from what any plan needs (you "
  "are not shown any plan outcome): the stated draw's absolute size (a "
  "founder drawing $200k can defer most of it; one drawing $30k is near "
  "subsistence already and can defer little), the business's scale and "
  "stage, and what founders of businesses like this actually do. A small "
  "deferral honestly judged beats a large one that leaves the founder "
  "unable to pay rent.\n"
  "The deferral is TEMPORARY: a bounded window, then a visible recovery "
  "ramp back to the full stated draw. If no deferral is realistic for this "
  "founder, say 0 — that is a perfectly good answer.\n"
  "Call submit_owner_draw_judgment exactly once."
)


def _build_user_prompt(
  *,
  business_identity: Dict[str, Any],
  owner_context: Dict[str, Any],
) -> str:
  lines: List[str] = []
  lines.append("BUSINESS IDENTITY (judge from this):")
  lines.append(json.dumps(business_identity, ensure_ascii=False, default=str))
  lines.append("")
  lines.append(
    "OWNER CONTEXT (the STATED draw is a fact; you are scheduling its "
    "timing, not changing it):"
  )
  lines.append(json.dumps(owner_context, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_owner_draw_judgment_once(
  *,
  business_identity: Dict[str, Any],
  owner_context: Dict[str, Any],
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE owner-draw judgment call; return ``{ok, judgment, error}``
  where ``judgment`` = {max_deferral_fraction, deferral_quarters,
  recovery_quarters, rationale}, already clamped inside the rails.

  ``ok=False`` -> the caller keeps the lever CLOSED (no deferral)."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "judgment": None, "error": "openai_api_key_unset"}

  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": _build_user_prompt(
        business_identity=business_identity, owner_context=owner_context,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_owner_draw_judgment"}},
    "seed": int(seed),
  }
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  try:
    resp = http_fn(
      url=_OPENAI_URL, headers=headers, payload=payload,
      timeout_seconds=timeout_seconds,
      retryable_status=(429, 500, 502, 503, 504), max_attempts=3,
    )
  except Exception as exc:
    return {"ok": False, "judgment": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "judgment": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "judgment": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(parsed, dict):
    return {"ok": False, "judgment": None, "error": "no_judgment_in_tool_call"}
  try:
    frac = float(parsed.get("max_deferral_fraction"))
    window = int(parsed.get("deferral_quarters"))
    recovery = int(parsed.get("recovery_quarters"))
  except (TypeError, ValueError):
    return {"ok": False, "judgment": None, "error": "judgment_fields_not_numeric"}

  # ENFORCE the rails: bounded, temporary, recovered.
  frac = min(max(frac, 0.0), MAX_DEFERRAL_FRACTION_RAIL)
  window = min(max(window, 0), MAX_DEFERRAL_QUARTERS_RAIL)
  recovery = max(recovery, MIN_RECOVERY_QUARTERS_RAIL)
  if window + recovery > FULL_COMP_BY_QUARTER_RAIL:
    window = max(0, FULL_COMP_BY_QUARTER_RAIL - recovery)

  return {
    "ok": True,
    "judgment": {
      "max_deferral_fraction": frac,
      "deferral_quarters": window,
      "recovery_quarters": recovery,
      "rationale": str(parsed.get("rationale") or "")[:400],
    },
    "error": None,
  }


def owner_draw_factors_by_quarter(
  *,
  deferral_fraction: float,
  deferral_quarters: int,
  recovery_quarters: int,
  horizon: int = 20,
) -> Dict[int, float]:
  """The deferral SCHEDULE: comp factor per quarter. (1 - d) during the
  window, linear recovery back to 1.0 across the recovery ramp, full stated
  comp after — the catch-up is explicit in the trajectory."""
  d = min(max(float(deferral_fraction), 0.0), MAX_DEFERRAL_FRACTION_RAIL)
  w = min(max(int(deferral_quarters), 0), MAX_DEFERRAL_QUARTERS_RAIL)
  r = max(int(recovery_quarters), MIN_RECOVERY_QUARTERS_RAIL)
  factors: Dict[int, float] = {}
  for q in range(1, horizon + 1):
    if q <= w:
      factors[q] = 1.0 - d
    elif q <= w + r:
      step = (q - w) / float(r)
      factors[q] = (1.0 - d) + d * step
    else:
      factors[q] = 1.0
  return factors


__all__ = [
  "gpt_author_owner_draw_judgment_once",
  "owner_draw_factors_by_quarter",
  "MAX_DEFERRAL_FRACTION_RAIL",
  "MAX_DEFERRAL_QUARTERS_RAIL",
  "MIN_RECOVERY_QUARTERS_RAIL",
  "FULL_COMP_BY_QUARTER_RAIL",
]
