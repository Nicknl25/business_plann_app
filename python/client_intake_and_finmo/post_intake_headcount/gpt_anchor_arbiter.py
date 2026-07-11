"""GPT arbitration of DEGENERATE cost-anchor disagreements (band-fitting).

Bounds are only as real as their anchors. The proportional band-scaling in
band_fitting rescales the cohort envelope to the operator's stated cost level;
when the two sides disagree so radically that the rescaled band no longer even
OVERLAPS the raw cohort band, one of them is garbage -- and Python cannot tell
WHICH:

  - Luna: $1,200/yr stated opex -> a 0.07-0.18% SGA band no retailer on earth
    runs at. The ANCHOR is garbage; the cohort is right.
  - Golden Ring: 28% stated COGS vs a 55-86% manufacturing-flavored cohort
    band. The COHORT is inapplicable (a walk-in donut counter is retail, not
    a packaged-bread factory); the operator is right.

Same trap as the OEWS occupation list: the cohort is a statistical shadow of
the NAICS code, not of THIS business. Believability is an identity judgment,
so the identity-aware executive (GPT) arbitrates: Python DETECTS the
disagreement (cohort-overlap test, no tuned threshold), GPT JUDGES which side
a lender would believe for this business, Python ENFORCES the verdict inside
the disagreement interval (a custom level can never leave [operator, cohort]
-- rogue answers are clamped, never trusted).

Determinism: one call per business, routed through post_openai_with_retries,
so the verdict rides the GPT response lock (run-once-and-lock). A failed call
falls back CONSERVATIVELY: a below-cohort anchor keeps the raw cohort band
(higher costs -- can never manufacture viability); an above-cohort anchor
keeps the operator's stated spend (also the expensive side).
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
    "name": "submit_anchor_verdicts",
    "description": (
      "Submit one verdict per disputed metric. Call exactly once, covering "
      "every metric_key listed in the disagreements."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "verdicts": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "metric_key": {
                "type": "string",
                "description": "Echo the metric_key from the disagreement exactly.",
              },
              "verdict": {
                "type": "string",
                "enum": ["operator", "cohort", "custom"],
                "description": (
                  "'operator' = the operator's stated level is what a lender "
                  "would believe for THIS business (the cohort band does not "
                  "apply to its actual operating model). 'cohort' = the "
                  "operator's number is not credible (data error / incomplete "
                  "entry); use the industry band. 'custom' = neither is right; "
                  "supply custom_level."
                ),
              },
              "custom_level": {
                "type": "number",
                "description": (
                  "Only with verdict='custom': the defensible annual level for "
                  "this metric as a fraction of revenue (e.g. 0.09 = 9%). Must "
                  "lie between the operator level and the cohort band."
                ),
              },
              "rationale": {
                "type": "string",
                "description": "One sentence: why a lender would believe this level for THIS business.",
              },
            },
            "required": ["metric_key", "verdict"],
          },
        },
      },
      "required": ["verdicts"],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the executive arbitrating COST-ANCHOR DISPUTES for a specific "
  "business's financial plan. For each disputed metric you are given the "
  "operator's STATED level (as a fraction of revenue, with the implied annual "
  "dollars) and the INDUSTRY COHORT band for the business's NAICS code. They "
  "disagree so radically that one of them must be wrong.\n"
  "Judge from the BUSINESS IDENTITY (what it does at the point of sale, its "
  "scale, its operating model) -- NOT from the NAICS label. Cohort bands are "
  "statistical shadows of the code and are often manufacturing- or public-"
  "company-flavored even when the business is a small walk-in shop.\n"
  "THE TEST: which level would a small-business LENDER believe when reading "
  "this plan?\n"
  "- An operator level that is lean-but-real for this operating model (a B2B "
  "shop with near-zero marketing; a retail counter whose food cost undercuts "
  "a factory cohort) -> verdict 'operator'.\n"
  "- An operator level NO business of this kind can really run at (total G&A "
  "of a few hundred dollars a year -- less than one month of its own rent; a "
  "cost line that is clearly a data-entry slip or an incomplete answer) -> "
  "verdict 'cohort', or 'custom' with the level such a business realistically "
  "runs at.\n"
  "KNOW WHAT EACH LINE CONTAINS in THIS model before judging: "
  "cogs_percent_of_revenue is materials/merchandise/direct supplies ONLY -- "
  "direct LABOR is NOT in it (payroll is a separate row); cohort COGS "
  "statistics usually bundle direct labor in, so they run far above this "
  "model's definition for labor-heavy producers (a machine shop's stated "
  "35% materials-only COGS is consistent with a 60%+ all-in cohort figure "
  "-- the operator is right, not the cohort). sga_percent_of_revenue is "
  "residual admin overhead ONLY -- it excludes payroll, rent, and "
  "marketing, which cohort 'SG&A' statistics usually include. Compare the "
  "operator's number to the cohort ONLY after accounting for what each "
  "actually contains.\n"
  "Never choose a level to make the plan LOOK viable; choose the level that "
  "is TRUE for this business. Call submit_anchor_verdicts exactly once with "
  "one verdict per disputed metric."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  disagreements: List[Dict[str, Any]],
) -> str:
  lines: List[str] = []
  lines.append("ENRICHED BUSINESS COMPACT (business reality -- judge from this):")
  lines.append(json.dumps(compact, ensure_ascii=False, default=str))
  lines.append("")
  lines.append(
    "DISPUTED COST ANCHORS (operator level vs industry cohort band; all values "
    "are fractions of revenue):"
  )
  lines.append(json.dumps(disagreements, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_arbitrate_cost_anchors_once(
  *,
  compact: Dict[str, Any],
  disagreements: List[Dict[str, Any]],
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE arbitration call; return ``{ok, verdicts, error}`` where
  ``verdicts`` is ``{metric_key: {verdict, custom_level, rationale}}``.

  ``ok=False`` on missing key / HTTP error / malformed tool call; the caller
  applies the conservative default per disagreement side."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "verdicts": None, "error": "openai_api_key_unset"}

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
        compact=compact, disagreements=disagreements,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_anchor_verdicts"}},
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
    return {"ok": False, "verdicts": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "verdicts": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "verdicts": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(parsed, dict) or not isinstance(parsed.get("verdicts"), list):
    return {"ok": False, "verdicts": None, "error": "no_verdicts_in_tool_call"}
  verdicts: Dict[str, Dict[str, Any]] = {}
  for row in parsed["verdicts"]:
    if not isinstance(row, dict):
      continue
    mk = str(row.get("metric_key") or "").strip()
    v = str(row.get("verdict") or "").strip().lower()
    if not mk or v not in ("operator", "cohort", "custom"):
      continue
    verdicts[mk] = {
      "verdict": v,
      "custom_level": row.get("custom_level"),
      "rationale": str(row.get("rationale") or "")[:300],
    }
  if not verdicts:
    return {"ok": False, "verdicts": None, "error": "no_valid_verdicts"}
  return {"ok": True, "verdicts": verdicts, "error": None}


__all__ = ["gpt_arbitrate_cost_anchors_once"]
