"""GPT-authored revenue drivers (revenue-authoring design, settled with Nick).

Revenue is categorically different from every other lever: it is the ROOT the
whole plan derives from, and for these private businesses NO cohort/band data
can author it. So the EXECUTIVE (GPT) AUTHORS the revenue DRIVERS — per quarter
unit_price, capacity (units/period), and utilization across the 20-quarter ramp
— grounded in the enriched business compact (ops + team + target market +
demand sizing). PYTHON computes the resulting revenue line from those drivers
(revenue[q] = capacity[q] x utilization[q] x unit_price[q], the model_input
revenue formula). This is the same Python-computes-from-GPT-authored-drivers
pattern used for payroll; here revenue is the root, payroll grounds to it.

The compact is the GUARDRAIL: GPT must author from what the business can really
do (price the market bears, reachable demand, capacity it can staff/ramp to) —
not push numbers to manufacture viability. price/utilization/capacity have no
cohort bands BECAUSE they were never meant to be band-targeted; they are GPT's
revenue-authoring inputs.

Operator framing (extracted from the legacy operations_agent, judge-era only):
think about what this business can realistically ABSORB across 20 quarters —
link the volume ramp to staffing, capacity, and timing; do not author a ramp the
operation cannot support.

This module makes ONE structured tool-call per attempt (mirrors
gpt_payroll_author). No key / HTTP failure -> ok=False. It does NOT mutate
state and does NOT validate; the caller computes the line + writes model_input.
When re-invoked by the cascade (revenue is the binding constraint), the caller
passes ``failing_state`` so GPT re-authors grounded in why it's being asked to
reconsider.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 90.0
_HORIZON = 20


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_revenue_drivers",
    "description": (
      "Submit the authored revenue drivers for the primary line of business. "
      "Call exactly once with a row for every quarter Q1..Q20."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "lob_name": {"type": "string", "description": "The line of business this revenue is for."},
        "unit_name": {"type": "string", "description": "The unit sold (e.g. donut, engagement, subscription-month)."},
        "quarters": {
          "type": "array",
          "description": (
            "Exactly 20 rows, one per quarter Q1..Q20, defining the revenue ramp. "
            "Quarterly revenue = capacity_units_per_period x utilization_rate x unit_price."
          ),
          "items": {
            "type": "object",
            "properties": {
              "q": {"type": "integer", "minimum": 1, "maximum": 20},
              "unit_price": {
                "type": "number", "minimum": 0,
                "description": "Price per unit the target market will bear (grounded in positioning).",
              },
              "capacity_units_per_period": {
                "type": "number", "minimum": 0,
                "description": (
                  "Units the business can PRODUCE/SERVE this quarter at full "
                  "utilization — grounded in staffing/capacity it can actually "
                  "ramp to (labor, equipment, facility). Non-decreasing as it scales."
                ),
              },
              "utilization_rate": {
                "type": "number", "minimum": 0, "maximum": 1.0,
                "description": "Fraction of capacity actually sold — bounded by reachable demand.",
              },
            },
            "required": ["q", "unit_price", "capacity_units_per_period", "utilization_rate"],
          },
        },
        "demand_grounding": {
          "type": "string",
          "description": (
            "How the ramp respects reachable market / expected units from the "
            "compact's market_demand (cite the numbers you anchored to)."
          ),
        },
        "capacity_grounding": {
          "type": "string",
          "description": "How the capacity ramp is supported by staffing/facility (link to team).",
        },
        "pricing_rationale": {"type": "string", "description": "Why this price fits the positioning/market."},
      },
      "required": [
        "lob_name", "unit_name", "quarters",
        "demand_grounding", "capacity_grounding", "pricing_rationale",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the executive authoring the REVENUE DRIVERS for a post-intake business "
  "plan. Revenue is the ROOT of the whole plan — it cannot be derived from industry "
  "bands; only you can reason about what THIS specific business can actually sell. "
  "You are given an enriched business compact: what it sells and how it prices "
  "(operating model), who runs it (team), who the customer is (target market), and "
  "how big the reachable market is and the demand it implies (market demand). "
  "Author the per-quarter revenue ramp across 20 quarters. Quarterly revenue = "
  "capacity_units_per_period x utilization_rate x unit_price.\n"
  "GROUNDING IS MANDATORY — author only what the business can really do:\n"
  "1. unit_price: AUTHOR the price the business can realistically charge, grounded in "
  "the market portrait — positioning, consumer_type, the audience income band, the "
  "segments, and the actual product mix. The intake price (and any price quoted in the "
  "positioning text) is a REFERENCE you author FROM, NOT a fixed value you are locked "
  "to: if the product mix and market support a different price, set it. In particular, "
  "if the business sells a MIX (e.g. classic AND specialty/premium items), author a "
  "BLENDED price across the mix, not the lowest single-item price. GUARDRAIL: raise "
  "price ONLY because the market portrait supports it (premium positioning, income, "
  "specialty mix, comparable pricing) — NEVER to manufacture viability. A value / "
  "price-sensitive portrait → hold price low; a premium / decent-income portrait → you "
  "may set it higher. The compact is the ceiling on what you can justify.\n"
  "2. capacity_units_per_period: what the business can PRODUCE/SERVE given the team "
  "and facility it can realistically staff/ramp to. Think like an operator: a ramp "
  "the operation cannot support is invalid. Capacity is non-decreasing as it scales.\n"
  "3. utilization_rate: the fraction of capacity you actually sell, BOUNDED by the "
  "reachable market / expected units in market_demand. Do not sell more than demand "
  "supports.\n"
  "4. Build a believable RAMP: early quarters lower (ramp-up), growing as the "
  "business establishes itself — within demand and capacity limits.\n"
  "If you are given a CURRENT FAILING FORECAST, you are being asked to RE-AUTHOR "
  "revenue because cost/structural levers could not make the forecast viable. "
  "Re-author from REAL business changes you can justify from the compact (a price "
  "the market still bears, added capacity you can staff, faster but feasible ramp) "
  "— never 'raise revenue because we need viability.' If the business genuinely "
  "cannot reach viability within what the compact allows, author the most credible "
  "ramp the business can truly achieve.\n"
  "Call submit_revenue_drivers exactly once with all 20 quarters."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  current_revenue_reference: Optional[Dict[str, Any]],
  failing_state: Optional[Dict[str, Any]],
) -> str:
  lines: List[str] = []
  lines.append("ENRICHED BUSINESS COMPACT (your full view of business reality — the guardrail):")
  lines.append(json.dumps(compact, ensure_ascii=False, default=str))
  if current_revenue_reference:
    lines.append("")
    lines.append("CURRENT REVENUE DRIVERS (intake baseline; reference, you may revise):")
    lines.append(json.dumps(current_revenue_reference, ensure_ascii=False, default=str))
  if failing_state:
    lines.append("")
    lines.append(
      "CURRENT FAILING FORECAST — the cascade could not make the plan viable with "
      "cost/structural levers; revenue is the binding constraint. Re-author the "
      "revenue ramp grounded in real, justifiable business changes (the compact is "
      "the limit). Here is why you are being asked to reconsider:"
    )
    lines.append(json.dumps(failing_state, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_revenue_drivers_once(
  *,
  compact: Dict[str, Any],
  current_revenue_reference: Optional[Dict[str, Any]] = None,
  failing_state: Optional[Dict[str, Any]] = None,
  previous_violations: Optional[List[Dict[str, Any]]] = None,
  model: Optional[str] = None,
  seed: int = 1729,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE GPT revenue-authoring call; return ``{ok, drivers, error}``.

  ``ok=False`` on missing key / HTTP error / malformed tool call. The caller
  computes the revenue line from ``drivers`` and writes model_input."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "drivers": None, "error": "openai_api_key_unset"}

  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  user_prompt = _build_user_prompt(
    compact=compact,
    current_revenue_reference=current_revenue_reference,
    failing_state=failing_state,
  )
  if previous_violations:
    user_prompt += (
      "\n\nYOUR PREVIOUS SUBMISSION WAS REJECTED. Fix exactly these problems and "
      "resubmit all 20 quarters:\n" + json.dumps(previous_violations[:20], ensure_ascii=False, default=str)
    )

  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user_prompt},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_revenue_drivers"}},
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
    return {"ok": False, "drivers": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "drivers": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
  except Exception:
    return {"ok": False, "drivers": None, "error": "non_json_body"}
  try:
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    drivers = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "drivers": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(drivers, dict) or not drivers.get("quarters"):
    return {"ok": False, "drivers": None, "error": "no_drivers_in_tool_call"}
  return {"ok": True, "drivers": drivers, "error": None}


__all__ = ["gpt_author_revenue_drivers_once"]
