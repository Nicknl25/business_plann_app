"""RESTRUCTURE SOLUTION REVIEW — GPT judges the solver's found design.

The searcher explored every configuration inside the executive's
reality bounds and returns the LEAST-aggressive viable one. Before the
real pipeline runs it, the executive reviews it in the only frame that
matters: IS THIS A REAL, LENDER-FUNDABLE BUSINESS? Not "does it pass"
(the solver already knows it passes its own arithmetic) — "would an
operator run this, would an underwriter fund this."

Outcomes:
  - approved            -> the design goes to the real pipeline.
  - rejected + tightened bounds -> the searcher re-runs inside the
    TIGHTER region (one round); the reviewer saying "1.75x volume is
    too much for this market" becomes a hard cap, not a suggestion.
  - rejected, no realistic tightening -> honest non-viable.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 90.0


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_solution_review",
    "description": "Submit the review verdict on the restructured design. Call exactly once.",
    "parameters": {
      "type": "object",
      "properties": {
        "approved": {
          "type": "boolean",
          "description": (
            "true if this restructured design is a REAL business a "
            "lender funds; false if any element is not credible."
          ),
        },
        "rationale": {
          "type": "string",
          "description": (
            "The reviewer's judgment in plain words (4-6 sentences): "
            "why this design is real and fundable — or exactly which "
            "element is not credible and why."
          ),
        },
        "tightened_lines": {
          "type": "array",
          "description": (
            "ONLY when approved=false because a line's move is too "
            "aggressive: the tighter caps the search must respect. "
            "Empty when approved or when no tightening would help."
          ),
          "items": {
            "type": "object",
            "properties": {
              "lob": {"type": "string"},
              "product": {"type": "string"},
              "volume_multiplier_max": {"type": ["number", "null"]},
              "price_multiplier_max": {"type": ["number", "null"]},
            },
            "required": ["lob", "product"],
          },
        },
        "revenue_story_required": {
          "type": "boolean",
          "description": (
            "Set true when rejecting a design because it reaches "
            "viability through cost compression alone: the re-search "
            "will then be REQUIRED to include at least one revenue-side "
            "move (pricing, volume/mix reallocation, or a new line) so "
            "the design carries a credible revenue and operations story."
          ),
        },
        "no_realistic_design_exists": {
          "type": "boolean",
          "description": (
            "true ONLY when approved=false AND no tightening would "
            "produce a real viable design — the honest terminal."
          ),
        },
      },
      "required": ["approved", "rationale", "tightened_lines", "revenue_story_required", "no_realistic_design_exists"],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER reviewing a restructured business "
  "design found by a deterministic solver searching inside reality "
  "bounds YOU authored. The solver's arithmetic already passes; that is "
  "not the question. The question is the one an underwriter asks: IS "
  "THIS A REAL BUSINESS? Judge the design as a whole:\n"
  "- Do the volume moves reflect demand that actually exists, or is "
  "the plan quietly assuming customers into existence?\n"
  "- Would a real operator run this configuration (team, space, mix), "
  "or is it a spreadsheet artifact?\n"
  "- Does the story hold together as a turnaround a lender reads and "
  "believes?\n"
  "You may APPROVE (it goes to the full planning system for the real "
  "verdict), REJECT WITH TIGHTER CAPS (name the line and the cap; the "
  "solver re-searches inside them), or conclude NO REALISTIC DESIGN "
  "EXISTS (the honest terminal). Approving a fake design and rejecting "
  "a real one are BOTH failures. Call submit_solution_review exactly "
  "once."
)


def gpt_review_solution_once(
  *,
  compact: Dict[str, Any],
  stated_facts: Dict[str, Any],
  bounds_rationale: Dict[str, Any],
  design_directive: Dict[str, Any],
  landed_projection: Dict[str, Any],
  model: Optional[str] = None,
  seed: int = 3181,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """ONE review call (locked). Returns ``{ok, review, error}``."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "review": None, "error": "openai_api_key_unset"}
  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries

  lines: List[str] = []
  lines.append("BUSINESS COMPACT (what this business IS):")
  lines.append(json.dumps(compact, ensure_ascii=False, default=str))
  lines.append("")
  lines.append("STATED FACTS (present-day reality):")
  lines.append(json.dumps(stated_facts, ensure_ascii=False, default=str))
  lines.append("")
  lines.append("YOUR REALITY BOUNDS (authored earlier; the search stayed inside them):")
  lines.append(json.dumps(bounds_rationale, ensure_ascii=False, default=str))
  lines.append("")
  lines.append("THE SOLVER'S FOUND DESIGN (the least-aggressive viable configuration):")
  lines.append(json.dumps(design_directive, ensure_ascii=False, default=str))
  lines.append("")
  lines.append("WHERE IT LANDS (the solver's projection at Q1/Q5/Q11/Q20):")
  lines.append(json.dumps(landed_projection, ensure_ascii=False, default=str))
  lines.append("")
  lines.append(
    "READING NOTE — cogs_pct is COGS as a share of REVENUE: when the "
    "design raises prices, the SAME physical unit cost divides by a "
    "higher price, so cogs_pct falls below the floor you authored at "
    "CURRENT prices. Physical unit costs are unchanged in this model — "
    "judge COGS realism in dollars per unit, not by the falling "
    "percentage."
  )

  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": "\n".join(lines)},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_solution_review"}},
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
    return {"ok": False, "review": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}
  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "review": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "review": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}
  if not isinstance(parsed, dict) or "approved" not in parsed:
    return {"ok": False, "review": None, "error": "no_review_in_tool_call"}
  return {"ok": True, "review": parsed, "error": None}


def apply_review_tightening(
  bounds: Dict[str, Any],
  review: Dict[str, Any],
) -> Dict[str, Any]:
  """Merge the reviewer's tighter caps into the bounds (tighter only —
  a review can never LOOSEN the executive's original region)."""
  import copy as _copy
  out = _copy.deepcopy(bounds)

  def _key(v: Any) -> str:
    return str(v or "").strip().casefold()

  by_key = {
    f"{_key(l.get('lob'))}/{_key(l.get('product'))}": l
    for l in (out.get("existing_lines") or [])
  }
  new_by_key = {
    f"{_key(nl.get('lob'))}/{_key(nl.get('product'))}": nl
    for nl in (out.get("new_line_candidates") or [])
  }
  for adj in (review.get("tightened_lines") or []):
    if not isinstance(adj, dict):
      continue
    adj_key = f"{_key(adj.get('lob'))}/{_key(adj.get('product'))}"
    line = by_key.get(adj_key)
    if isinstance(line, dict):
      for field in ("volume_multiplier_max", "price_multiplier_max"):
        try:
          new_cap = float(adj.get(field)) if adj.get(field) is not None else None
        except (TypeError, ValueError):
          continue
        if new_cap is not None and new_cap < float(line.get(field) or 1.0):
          line[field] = max(1.0, round(new_cap, 4))
      continue
    # A tightened NEW line: a volume cap < 1 scales its market revenue
    # cap down (the reviewer saying "half that ramp is what's real").
    new_line = new_by_key.get(adj_key)
    if isinstance(new_line, dict):
      try:
        vol_cap = float(adj.get("volume_multiplier_max")) if adj.get("volume_multiplier_max") is not None else None
      except (TypeError, ValueError):
        vol_cap = None
      if vol_cap is not None and 0.0 < vol_cap < 1.0:
        try:
          rev_max = float(new_line.get("q11_quarterly_revenue_max") or 0.0)
        except (TypeError, ValueError):
          rev_max = 0.0
        if rev_max > 0.0:
          new_line["q11_quarterly_revenue_max"] = round(rev_max * vol_cap, 2)
  return out


__all__ = [
  "gpt_review_solution_once",
  "apply_review_tightening",
]
