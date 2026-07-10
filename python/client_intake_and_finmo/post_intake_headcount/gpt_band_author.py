"""The executive-manager's COST-STRUCTURE FORECAST (managerial shaping).

The old design handed GPT a flat cohort box per metric and asked for a
"step trajectory" inside it. The result was structurally rigid: a
20-quarter forecast frozen at startup ratios (marketing never
normalizes, G&A never gains operating leverage) with phantom cohort
lines (a boutique carrying R&D) alive because nothing could kill them.
Values pinned flat at box edges are a WRONG forecast — a business
matures over five years.

This module gives the executive MANAGERIAL AGENCY instead: it reasons
over the whole business like a competent operator and authors, per cost
line:

  - applicable: whether this business genuinely incurs the line at all
    (kill the cohort ghosts), and
  - a MATURATION PATH via three anchors (Q1 / Q11 / Q20) with a
    rationale a lender would accept.

THE FENCE is lender-defensibility, not a numeric box: every call must
be one a competent manager would make and could defend on the
business's merits. The prompt gives the executive NO viability status
— it cannot shape numbers to force a pass because it does not know
what passing requires. Python then enforces the FACTS (Q1 must reflect
operator-stated, arbitration-credible present-day costs; a stated cost
cannot be killed) and interpolates the anchors into the 20-quarter
trajectory. Cohort bands ride along as REFERENCE CONTEXT only.

Determinism: the call rides the GPT response lock (run-once-and-lock)
like every other executive judgment — same inputs, same locked
managerial call, byte-identical runs.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 90.0
_HORIZON = 20

# The cost-ratio metrics the manager forecasts (each a fraction-of-revenue)
# plus the net-income / EBITDA margin spines (the viability checkpoint the
# manager expects the cost path to produce).
BAND_METRIC_KEYS = (
  "cogs_percent_of_revenue",
  "marketing_percent_of_revenue",
  "sga_percent_of_revenue",
  "r_and_d_percent_of_revenue",
  "net_income_margin",
  "ebitda_margin",
)


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_cost_structure_forecast",
    "description": (
      "Submit the managerial cost-structure forecast: one entry per "
      "metric_key listed in the request. Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "lines": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "metric_key": {
                "type": "string",
                "description": "Echo the metric_key exactly.",
              },
              "applicable": {
                "type": "boolean",
                "description": (
                  "false = this business genuinely does not incur this line "
                  "(e.g. R&D for a clothing boutique) — the line is removed "
                  "from the plan. Margin spines (net_income_margin, "
                  "ebitda_margin) are always applicable."
                ),
              },
              "q1_level": {
                "type": "number",
                "description": (
                  "The level TODAY (fraction of revenue; margins may be "
                  "negative). Must reflect the operator's stated present-day "
                  "costs where stated — the present is a fact, not a lever."
                ),
              },
              "q11_level": {
                "type": "number",
                "description": "The level at Q11 (~year 3) as the business matures.",
              },
              "q20_level": {
                "type": "number",
                "description": "The mature level at Q20 (~year 5).",
              },
              "rationale": {
                "type": "string",
                "description": (
                  "The manager's defense of this path to a lender, on the "
                  "business's merits (2-3 sentences)."
                ),
              },
            },
            "required": ["metric_key", "applicable", "q1_level", "q11_level", "q20_level", "rationale"],
          },
        },
      },
      "required": ["lines"],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER of this business, forecasting its cost "
  "structure across a 20-quarter (5-year) plan the way a competent operator "
  "would. You understand what the business IS, how it matures, what is real "
  "and what is a statistical ghost — and you shape the forecast accordingly.\n"
  "THE FENCE: every call must be one you could defend to a small-business "
  "LENDER on the business's merits. Not 'what makes the plan look good' — "
  "you are not told whether this plan passes anything, and you must never "
  "shape a number to force an outcome. Defensible on merits, or not at all.\n"
  "HOW A MANAGER FORECASTS:\n"
  "1. KILL PHANTOM LINES: the cohort reference bands come from NAICS "
  "statistics and often carry lines this business does not incur (R&D for a "
  "clothing boutique; COGS for a pure-service firm). If the business "
  "genuinely does not spend on a line, mark it applicable=false. Never kill "
  "a line the operator actually reported paying.\n"
  "2. Q1 IS A FACT: where the operator stated a current cost level (marked "
  "CREDIBLE in the data), your Q1 must reflect it. You are forecasting the "
  "future, not editing the present.\n"
  "3. MODEL MATURATION: startup-phase ratios NORMALIZE as the business "
  "establishes. Marketing runs hot early and settles toward the level a "
  "mature operation sustains. G&A gains operating leverage — fixed admin "
  "spreads over growing revenue. COGS may improve modestly with buying "
  "power. Holding a startup ratio flat for five years is a WRONG forecast; "
  "so is a hockey stick no lender would believe. Anchor Q1 to today, Q11 to "
  "the establishing business, Q20 to maturity.\n"
  "4. THE SPINES FOLLOW THE COSTS: forecast net_income_margin and "
  "ebitda_margin as the arithmetic consequence you expect from your cost "
  "path and the business's payroll/rent reality — loss-tolerant early, "
  "climbing as the costs normalize. By Q11 net income must be leading into "
  "positive territory (a plan that loses money for five years is not "
  "fundable) — but reach that through the cost path's merits, never by "
  "asserting margins the costs cannot produce.\n"
  "5. THINK IN DOLLARS, NOT JUST RATIOS: translate every ratio into annual "
  "dollars against the revenue line and sanity-check it at this business's "
  "scale. G&A of 37% on a $1M boutique is $370k of admin overhead for a "
  "shop with a handful of staff — absurd, whatever the cohort says. A "
  "ratio that fails the dollar test fails the lender test.\n"
  "The cohort reference bands are CONTEXT — often factory- or public-"
  "company-flavored. Where they fit this business, use them; where they "
  "don't, your judgment governs and your rationale defends it.\n"
  "Call submit_cost_structure_forecast exactly once, one entry per "
  "requested metric."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  revenue_line: List[float],
  industry_envelope: Dict[str, Any],
  operator_facts: Optional[Dict[str, Any]] = None,
) -> str:
  lines: List[str] = []
  lines.append("ENRICHED BUSINESS COMPACT (what this business IS — judge from this):")
  lines.append(json.dumps(compact, ensure_ascii=False, default=str))
  lines.append("")
  lines.append("AUTHORED REVENUE LINE (quarterly; the scale your ratios apply to):")
  lines.append(json.dumps([round(float(v), 2) for v in (revenue_line or [])], default=str))
  lines.append("")
  if operator_facts:
    lines.append(
      "OPERATOR-STATED PRESENT-DAY COST LEVELS (fractions of revenue; "
      "entries marked credible=true are FACTS your Q1 must reflect; "
      "credible=false were judged data errors and are shown for context):"
    )
    lines.append(json.dumps(operator_facts, ensure_ascii=False, default=str))
    lines.append("")
  lines.append(
    "COHORT REFERENCE BANDS per metric (fraction of revenue; {min,target,max}). "
    "REFERENCE CONTEXT ONLY — not walls. Forecast every metric listed here:"
  )
  lines.append(json.dumps(industry_envelope, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_fitted_bands_once(
  *,
  compact: Dict[str, Any],
  revenue_line: List[float],
  industry_envelope: Dict[str, Any],
  previous_violations: Optional[List[Dict[str, Any]]] = None,
  operator_facts: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE managerial cost-structure forecast call; return
  ``{ok, forecast, error}`` where ``forecast`` is a list of
  ``{metric_key, applicable, q1_level, q11_level, q20_level, rationale}``.

  ``ok=False`` on missing key / HTTP error / malformed tool call. The caller
  interpolates + validates the anchors (fact-grounding, Q11 rule)."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "forecast": None, "error": "openai_api_key_unset"}

  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  user_prompt = _build_user_prompt(
    compact=compact, revenue_line=revenue_line,
    industry_envelope=industry_envelope, operator_facts=operator_facts,
  )
  if previous_violations:
    user_prompt += (
      "\n\nYOUR PREVIOUS SUBMISSION WAS REJECTED. Fix exactly these problems and "
      "resubmit every metric:\n"
      + json.dumps(previous_violations[:20], ensure_ascii=False, default=str)
    )

  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user_prompt},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_cost_structure_forecast"}},
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
    return {"ok": False, "forecast": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "forecast": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "forecast": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(parsed, dict) or not isinstance(parsed.get("lines"), list) or not parsed.get("lines"):
    return {"ok": False, "forecast": None, "error": "no_forecast_lines_in_tool_call"}
  return {"ok": True, "forecast": parsed.get("lines"), "error": None}


__all__ = ["gpt_author_fitted_bands_once", "BAND_METRIC_KEYS"]
