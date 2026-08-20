"""GPT expert estimate of CUSTOMER RETENTION, for the marketing schedule.

Nick's ruling (R-MKTG-03): retention cannot fall out of the arithmetic. One
settled number per quarter solves for one unknown, and that unknown is CAC. So
retention is an ANCHORED, DISCLOSED assumption — GPT uses its own knowledge and
the business model to produce it, the same way the valuation sheet handles its
assumption inputs.

AND THE DISCLOSURE IS DIFFERENT FROM THE VALUATION SHEET'S, DELIBERATELY. The
valuation constants cite named third parties — Damodaran, FRED, Kroll,
BizBuySell — and that is what makes them hold up. **A GPT-derived retention is
an expert estimate, not a sourced figure, and this module never dresses it as
one.** It returns ``basis_detail="expert_estimate"`` and a source string that
says so in words. There is no citation field to fill in, because there is no
citation.

Determinism: one call per business, routed through ``post_openai_with_retries``
so the verdict rides the GPT response lock. A failed call returns ``ok=False``
and the schedule degrades to its exact half (class ``not_modelled``) rather
than substituting a silent default — a wrong retention would propagate into
customers, new customers and CAC, which are four of the schedule's eight lines.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MODEL = "gpt-4o"

#: Retention outside this band is not a business estimate, it is a mistake.
#: Clamped rather than trusted, on the house rule that a rogue answer is
#: bounded and never believed.
_MIN_RETENTION = 0.0
_MAX_RETENTION = 0.98

_SYSTEM_PROMPT = (
  "You estimate CUSTOMER RETENTION for small businesses, for financial "
  "modelling. You are given a business's model and operating shape. Return the "
  "share of this quarter's customers who return NEXT QUARTER, as a decimal "
  "between 0 and 1.\n\n"
  "Judge from the business model, not from optimism:\n"
  "- A subscription or membership business retains most customers quarter to "
  "quarter (high).\n"
  "- A recurring personal service with a natural cadence — grooming, salon, "
  "lawn care, cleaning — retains a solid majority.\n"
  "- A transactional retail or hospitality business retains far fewer, because "
  "a customer's return is occasional rather than scheduled.\n"
  "- A project business — legal matters, construction, consulting engagements — "
  "retains fewest, because the engagement ends.\n\n"
  "You are producing an EXPERT ESTIMATE, not a sourced statistic. Do not cite "
  "studies, reports, or figures you cannot verify. Give the number and your "
  "reasoning from the business model in one or two sentences."
)

_SUBMIT_TOOL = {
  "type": "function",
  "function": {
    "name": "submit_retention_estimate",
    "description": "Submit the quarter-over-quarter customer retention estimate.",
    "parameters": {
      "type": "object",
      "properties": {
        "retention_rate": {
          "type": "number",
          "description": "Share of this quarter's customers who return next quarter, 0 to 1.",
        },
        "rationale": {
          "type": "string",
          "description": "One or two sentences reasoning from the business model.",
        },
        "confidence_tier": {
          "type": "string",
          "enum": ["low", "medium", "high"],
          "description": "How confident this estimate is, given the business model.",
        },
      },
      "required": ["retention_rate", "rationale", "confidence_tier"],
      "additionalProperties": False,
    },
  },
}


def _resolve_model(model: Optional[str]) -> str:
  return (model or os.getenv("OPENAI_MODEL") or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _build_user_prompt(*, compact: Dict[str, Any]) -> str:
  lines = ["Business:"]
  for key in ("business_type", "business_naics_6", "market_basis_type",
              "consumer_type", "geographic_scope", "business_stage"):
    value = compact.get(key)
    if value not in (None, ""):
      lines.append(f"  {key}: {value}")
  products = compact.get("products") or []
  if products:
    lines.append("Revenue lines:")
    for product in products[:8]:
      lines.append(
        f"  - {product.get('product_name')} at {product.get('unit_price')} per "
        f"{product.get('unit_cadence') or 'unit'}, "
        f"{product.get('units_per_period_capacity')} per period capacity"
      )
  repeat = compact.get("implied_repeat_units_per_customer")
  if repeat:
    lines.append(
      f"The plan implies about {repeat:.1f} purchases per customer per year, "
      f"which is a signal of how often a customer comes back."
    )
  lines.append(
    "\nEstimate the quarter-over-quarter customer retention rate for THIS "
    "business and submit it."
  )
  return "\n".join(lines)


def gpt_author_retention_once(
  *,
  compact: Dict[str, Any],
  model: Optional[str] = None,
  seed: int = 1741,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE call; return ``{ok, retention_rate, rationale, confidence_tier,
  model, error}``.

  ``ok=False`` on missing key / HTTP error / malformed tool call. The caller
  degrades the schedule rather than substituting a default.
  """
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "retention_rate": None, "error": "openai_api_key_unset"}

  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  resolved_model = _resolve_model(model)
  payload = {
    "model": resolved_model,
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": _build_user_prompt(compact=compact)},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_retention_estimate"}},
    "seed": int(seed),
  }
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  try:
    response = http_fn(
      url=_OPENAI_URL, headers=headers, payload=payload,
      timeout_seconds=timeout_seconds,
      retryable_status=(429, 500, 502, 503, 504), max_attempts=3,
    )
  except Exception as exc:
    return {"ok": False, "retention_rate": None,
            "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(response, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "retention_rate": None,
            "error": f"http_status_{status}:{str(getattr(response, 'text', ''))[:300]}"}

  try:
    body = response.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    function = (tool_calls[0] or {}).get("function") if tool_calls else None
    raw_args = (function or {}).get("arguments")
    parsed = json.loads(raw_args) if isinstance(raw_args, str) else (
      raw_args if isinstance(raw_args, dict) else None)
  except Exception as exc:
    return {"ok": False, "retention_rate": None,
            "error": f"parse_error:{type(exc).__name__}:{str(exc)[:200]}"}

  if not isinstance(parsed, dict) or parsed.get("retention_rate") is None:
    return {"ok": False, "retention_rate": None, "error": "malformed_tool_call"}

  try:
    rate = float(parsed.get("retention_rate"))
  except (TypeError, ValueError):
    return {"ok": False, "retention_rate": None, "error": "retention_rate_not_numeric"}

  clamped = min(max(rate, _MIN_RETENTION), _MAX_RETENTION)
  return {
    "ok": True,
    "retention_rate": clamped,
    "retention_rate_raw": rate,
    "clamped": clamped != rate,
    "rationale": str(parsed.get("rationale") or "")[:500],
    "confidence_tier": str(parsed.get("confidence_tier") or "low"),
    "model": resolved_model,
    "error": None,
  }
