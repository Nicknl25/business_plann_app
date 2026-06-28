"""GPT-authored per-quarter band step-trajectories (band-fitting design).

The cohort/industry bands have the right SHAPE but the wrong SCALE for a
specific business: a law firm should not be driven toward 74% R&D just because
a NAICS default envelope allows it. Band-fitting fixes this so that, downstream,
"move the lever toward its band" finally means "move toward viable."

Revenue is the scaling anchor and the business compact is the guardrail. The
EXECUTIVE (GPT) AUTHORS, per cost-ratio metric (COGS / Marketing / G&A / R&D as
% of revenue) and for the net-income margin, the per-quarter STEP TRAJECTORY
across the 20-quarter horizon — loss-tolerant early, stepping toward viability.
PYTHON then VALIDATES every authored point against the scaled industry envelope
and the hard Q11 net-income rule (by Q11 the business must be leading into
positive net income; net income may not stay negative for ~5 years). GPT sets
the SHAPE within the bounds; Python ENFORCES the bounds.

This is the same Python-computes/validates-from-GPT-authored pattern used for
revenue authoring (gpt_revenue_author) and payroll. One structured tool-call per
attempt. No key / HTTP failure -> ok=False (caller keeps the raw bands).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 90.0
_HORIZON = 20

# The cost-ratio metrics GPT fits (each a fraction-of-revenue) plus the
# net-income margin trajectory (the viability spine + the Q11 checkpoint).
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


_QUARTER_ITEM: Dict[str, Any] = {
  "type": "object",
  "properties": {
    "q": {"type": "integer", "minimum": 1, "maximum": 20},
    "value": {
      "type": "number",
      "description": (
        "The fitted band TARGET for this metric in this quarter, as a fraction "
        "(e.g. 0.32 = 32% of revenue; for net_income_margin a negative value "
        "means a loss). This is the realistic level for THIS business, within "
        "the industry envelope you are given."
      ),
    },
  },
  "required": ["q", "value"],
}

_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_fitted_bands",
    "description": (
      "Submit the per-quarter fitted band trajectory for EVERY metric listed in "
      "the industry envelope. One entry per metric, each with all 20 quarters. "
      "Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "bands": {
          "type": "array",
          "description": (
            "One entry per metric_key in the industry envelope "
            "(cogs/marketing/sga/r_and_d percent_of_revenue + net_income_margin)."
          ),
          "items": {
            "type": "object",
            "properties": {
              "metric_key": {
                "type": "string",
                "description": "Echo the metric_key from the industry envelope exactly.",
              },
              "quarters": {
                "type": "array",
                "description": "Exactly 20 rows, one per quarter Q1..Q20, the fitted target trajectory.",
                "items": _QUARTER_ITEM,
              },
              "fit_rationale": {
                "type": "string",
                "description": "Why this trajectory fits THIS business (cite the compact + revenue).",
              },
            },
            "required": ["metric_key", "quarters"],
          },
        },
      },
      "required": ["bands"],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the executive FITTING the financial bands to a specific business. You "
  "are given (1) an enriched business compact (what it sells, team, market, demand), "
  "(2) the business's AUTHORED REVENUE line across 20 quarters (the scaling anchor), "
  "and (3) the INDUSTRY ENVELOPE per metric (min/target/max as a fraction of revenue) "
  "for cost ratios (COGS, Marketing, G&A, R&D) and the net-income AND EBITDA margins. "
  "The margin metrics (net_income_margin, ebitda_margin) are VIABILITY SPINES -- author "
  "them at the level THIS business can really reach (a healthy professional-services firm "
  "may run well above an industry-wide midpoint); ebitda_margin is always >= net_income_"
  "margin in the same quarter.\n"
  "The industry envelope has the right SHAPE but is a broad band for the whole "
  "industry — it is NOT automatically right for THIS business. Author, per metric, "
  "the per-quarter TARGET TRAJECTORY that actually fits this business.\n"
  "RULES (Python will ENFORCE these — author within them):\n"
  "1. GROUND IN THE BUSINESS: a metric the business does not really incur should be "
  "near the bottom of its envelope, not the middle. A law firm has ~no R&D or COGS; "
  "do not drift it toward an industry-wide midpoint. A value business holds marketing "
  "modest; a premium/brand business may spend more. Use the compact.\n"
  "2. STAY INSIDE THE ENVELOPE: every quarter value must be within [min, max] of that "
  "metric's industry envelope. The envelope is the outer bound; you choose WHERE "
  "inside it this business sits, per quarter.\n"
  "3. STEP, DON'T DRIFT: author a STAGE-SHIFTED, STEP-CHANGED trajectory — loss-"
  "tolerant early (costs can run higher / net income negative while ramping), then "
  "stepping toward viability as revenue builds. Not one flat line, not a smooth "
  "curve — deliberate steps.\n"
  "4. HARD Q11 NET-INCOME RULE: by Q11 the business must be LEADING INTO positive "
  "net income (net_income_margin >= 0 by Q11) and stay non-negative thereafter. Net "
  "income may be negative early but NOT for ~5 years. The cost-ratio trajectories must "
  "be consistent with hitting that (costs step DOWN as a share of revenue so the "
  "Q11 net-income checkpoint is reachable). Early downward steps in a cost ratio are "
  "fine; an early UP step is only acceptable if the net-income trajectory is still "
  "provably climbing toward the Q11 checkpoint.\n"
  "Call submit_fitted_bands exactly once with one entry per metric, each carrying all "
  "20 quarters."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  revenue_line: List[float],
  industry_envelope: Dict[str, Any],
) -> str:
  lines: List[str] = []
  lines.append("ENRICHED BUSINESS COMPACT (business reality — the guardrail):")
  lines.append(json.dumps(compact, ensure_ascii=False, default=str))
  lines.append("")
  lines.append("AUTHORED REVENUE LINE (quarterly, the scaling anchor):")
  lines.append(json.dumps([round(float(v), 2) for v in (revenue_line or [])], default=str))
  lines.append("")
  lines.append(
    "INDUSTRY ENVELOPE per metric (fraction of revenue; {min,target,max}). Fit "
    "WITHIN [min,max]; do not just copy target:"
  )
  lines.append(json.dumps(industry_envelope, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_fitted_bands_once(
  *,
  compact: Dict[str, Any],
  revenue_line: List[float],
  industry_envelope: Dict[str, Any],
  previous_violations: Optional[List[Dict[str, Any]]] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE GPT band-fitting call; return ``{ok, bands, error}``.

  ``ok=False`` on missing key / HTTP error / malformed tool call. The caller
  normalizes + validates ``bands`` against the envelope + the Q11 rule."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "bands": None, "error": "openai_api_key_unset"}

  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  user_prompt = _build_user_prompt(
    compact=compact, revenue_line=revenue_line, industry_envelope=industry_envelope,
  )
  if previous_violations:
    user_prompt += (
      "\n\nYOUR PREVIOUS SUBMISSION WAS REJECTED. Fix exactly these problems and "
      "resubmit all metrics x 20 quarters:\n"
      + json.dumps(previous_violations[:20], ensure_ascii=False, default=str)
    )

  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user_prompt},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_fitted_bands"}},
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
    return {"ok": False, "bands": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "bands": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
  except Exception:
    return {"ok": False, "bands": None, "error": "non_json_body"}
  try:
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "bands": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(parsed, dict) or not parsed.get("bands"):
    return {"ok": False, "bands": None, "error": "no_bands_in_tool_call"}
  return {"ok": True, "bands": parsed.get("bands"), "error": None}


__all__ = ["gpt_author_fitted_bands_once", "BAND_METRIC_KEYS"]
