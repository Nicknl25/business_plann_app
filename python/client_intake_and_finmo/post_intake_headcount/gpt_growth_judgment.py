"""The executive-manager's REVENUE GROWTH JUDGMENT (holistic revenue).

The deterministic revenue proposer is excellent at the MECHANICS —
anchoring Q1 to the operator's stated revenue, smooth tapered growth
under the QoQ cap, exact driver allocation — but dumb about the
BUSINESS: every plan grew on the same universal curve (6% -> 2.5% QoQ)
whether it was a saturated boutique or a booming startup.

Same split that fixed the cost structure: the MANAGER judges, the
MACHINE executes. This module is the judgment — how fast does THIS
business realistically grow given its actual market, defended to a
lender — and ``deterministic_revenue_proposer`` remains the sole
executor (anchor, smoothness, cap, allocation stay Python-owned;
GPT never touches the mechanics it was removed from).

THE FENCE — tighter than cost, because revenue is the root and the
easiest lever to fake viability with:
  1. VIABILITY-BLIND: the prompt never sees whether the plan passes
     anything; it cannot juice growth to force a pass.
  2. Q1 IS A HARD FACT: the judgment covers GROWTH only; the Q1 level
     stays anchored by the machine to stated current revenue (zero
     corridor width — the rule that caught the COGS fake-pass).
  3. LENDER-BELIEVABILITY RAIL: Python clamps the judged rates into
     [0, QOQ cap] — the machine's long-standing 7%/quarter ceiling
     (~31%/yr). The manager can only TIGHTEN the curve relative to the
     mechanical default's ceiling, never widen it. A rogue judgment
     cannot run away.
  4. DETERMINISTIC: one locked call (run-once-and-lock) like every
     other executive judgment; a failed call falls back to the
     universal mechanical defaults (today's exact behavior).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_growth_judgment",
    "description": "Submit the growth judgment for this business. Call exactly once.",
    "parameters": {
      "type": "object",
      "properties": {
        "year1_annual_growth": {
          "type": "number",
          "description": (
            "Realistic ANNUAL revenue growth rate over the first year or two "
            "(fraction: 0.12 = 12%/yr). Judge from this business's actual "
            "market, capacity, and stage — not from what any plan needs."
          ),
        },
        "mature_annual_growth": {
          "type": "number",
          "description": (
            "Realistic ANNUAL growth rate once established (~year 4-5), as a "
            "fraction. Mature businesses in most local markets grow single "
            "digits."
          ),
        },
        "rationale": {
          "type": "string",
          "description": (
            "The manager's defense of these rates to a lender, grounded in "
            "THIS business and its market (2-3 sentences)."
          ),
        },
      },
      "required": ["year1_annual_growth", "mature_annual_growth", "rationale"],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER of this business, judging how fast it can "
  "REALISTICALLY grow revenue over a 5-year plan — the way a competent "
  "operator would defend growth assumptions to a small-business LENDER.\n"
  "THE TEST: would a lender believe this growth for THIS business in THIS "
  "market? A downtown boutique in a competitive retail market grows single "
  "digit to low-double-digit annually; a capacity-constrained service "
  "practice grows with its ability to add providers; a genuinely early-"
  "stage business in an underserved market can grow faster — briefly. "
  "Forty-percent annual growth for a walk-in shop is a fantasy, whatever "
  "any spreadsheet wants.\n"
  "GROWTH IS BOUNDED BY THE MARKET, and your rationale must reason from "
  "the MARKET REALITY data you are given: revenue cannot outgrow the "
  "reachable market at a believable capture rate. If the plan already "
  "assumes a high capture rate, there is little room to grow by taking "
  "share — growth must then come from price, purchase frequency, or "
  "genuinely expanding reach, and you must say which. Judge a B2B "
  "business by account dynamics (few, large, slow, lumpy) and a B2C "
  "business by reach/repeat dynamics — the two grow DIFFERENTLY and your "
  "rationale should show which one this is.\n"
  "You are NOT told whether any plan passes or fails — judge the business "
  "and its market on their merits, never what a plan might need. Growth "
  "typically starts higher (small base, ramping awareness) and matures "
  "lower (market saturation, capacity limits).\n"
  "Call submit_growth_judgment exactly once."
)


# Market slices get their own labeled section (not buried in the compact
# JSON) so the judgment reads them as the BOUNDS they are.
_MARKET_SLICE_KEYS = ("target_market", "market_demand")


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  current_annual_revenue: Optional[float],
) -> str:
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
    MARKET_SEMANTICS_PRIMER,
  )
  _compact = dict(compact or {})
  market_reality = {k: _compact.pop(k) for k in _MARKET_SLICE_KEYS if k in _compact}
  lines: List[str] = []
  lines.append("BUSINESS COMPACT (what this business IS — identity, operations, team):")
  lines.append(json.dumps(_compact, ensure_ascii=False, default=str))
  lines.append("")
  if market_reality:
    lines.append(
      "MARKET REALITY (the bounds your growth judgment must respect — who "
      "the customers are, how many are reachable, what the plan already "
      "assumes captured):"
    )
    lines.append(json.dumps(market_reality, ensure_ascii=False, default=str))
    lines.append("")
    lines.append(MARKET_SEMANTICS_PRIMER)
    lines.append("")
  if current_annual_revenue:
    lines.append(
      f"CURRENT ANNUAL REVENUE (operator-stated/implied; the plan's Q1 is "
      f"anchored to this FACT and is not yours to move): "
      f"{round(float(current_annual_revenue), 2)}"
    )
  return "\n".join(lines)


def gpt_author_growth_judgment_once(
  *,
  compact: Dict[str, Any],
  current_annual_revenue: Optional[float] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE growth-judgment call; return ``{ok, judgment, error}`` where
  ``judgment`` = {year1_annual_growth, mature_annual_growth, rationale}
  (RAW — the caller converts to QoQ and clamps into the believability rail).

  ``ok=False`` -> the caller keeps the universal mechanical defaults."""
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
        compact=compact, current_annual_revenue=current_annual_revenue,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_growth_judgment"}},
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
    y1 = float(parsed.get("year1_annual_growth"))
    mat = float(parsed.get("mature_annual_growth"))
  except (TypeError, ValueError):
    return {"ok": False, "judgment": None, "error": "growth_rates_not_numeric"}
  return {
    "ok": True,
    "judgment": {
      "year1_annual_growth": y1,
      "mature_annual_growth": mat,
      "rationale": str(parsed.get("rationale") or "")[:400],
    },
    "error": None,
  }


def annual_to_qoq(annual: float) -> float:
  """Compound-consistent conversion: (1+annual)^(1/4) - 1. Negative annual
  judgments floor at 0 QoQ (the proposer's growth model does not shrink a
  business; a declining market shows up as ~zero growth, not negative
  revenue the working-capital machinery would misread)."""
  a = max(0.0, float(annual))
  return (1.0 + a) ** 0.25 - 1.0


__all__ = ["gpt_author_growth_judgment_once", "annual_to_qoq"]
