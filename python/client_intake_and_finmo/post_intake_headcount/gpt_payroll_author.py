"""GPT-authors-anchored round-1 payroll authoring (Lineage B).

The EXECUTIVE (GPT) authors the round-1 ``payroll_headcount_schedule``
contract — it decides which OEWS occupation titles to staff and the
ending FTE per title per quarter — grounded in the revenue-driven payroll
ANCHOR (``compute_round1_payroll_anchor``) handed in as non-binding
reference. PYTHON grounds (the anchor) and validates (the existing
``validate_payroll_headcount_contract_payload`` + builder, invoked by the
caller); on a validation failure the executive RE-AUTHORS with the
validator's structured feedback (bounded retries).

Division of labor (matches the contract schema, post_intake_mapping.py:
2051-2053): GPT owns the FTE staffing decision (ending_fte per title per
quarter); Python NORMALIZES the mechanical arithmetic (starting_fte, hires,
continuity) and validates. So GPT supplies ``ending_fte`` per row and may
leave ``starting_fte``/``hires`` at 0 — Python derives them from continuity.

Authority: docs/architecture/gpt_authors_payroll_anchored_scope.md.

This module makes ONE structured tool-call per attempt. No key / HTTP
failure -> ``ok=False`` (the caller falls back to the deterministic
no-executive producer). It does NOT mutate state and does NOT validate;
the caller (set_payroll_schedule) owns validate/build.
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
    "name": "submit_payroll_headcount_schedule",
    "description": (
      "Submit the authored round-1 payroll_headcount_schedule contract. "
      "Call exactly once with the full contract."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "payroll_headcount_grid": {
          "type": "array",
          "description": (
            "One row per (OEWS title, quarter) you staff. Provide a row for "
            "every quarter Q1..Q20 for each title you use; once a title "
            "starts, keep it active through Q20."
          ),
          "items": {
            "type": "object",
            "properties": {
              "q": {"type": "integer", "minimum": 1, "maximum": 20},
              "oews_occ_title": {
                "type": "string",
                "description": "Exact occ_title from the supplied oews_title_catalog.",
              },
              "starting_fte": {"type": "number", "minimum": 0},
              "hires": {"type": "number", "minimum": 0},
              "ending_fte": {
                "type": "number", "minimum": 0,
                "description": (
                  "YOUR staffing decision: FTE of this title at quarter end. "
                  "Must be NON-DECREASING across quarters for a given title "
                  "(hold or grow; never cut). You may leave starting_fte and "
                  "hires at 0 -- Python derives them from continuity."
                ),
              },
              "payroll_tax_benefits_pct": {"type": "number", "minimum": 0.12, "maximum": 0.35},
            },
            "required": ["q", "oews_occ_title", "starting_fte", "hires", "ending_fte", "payroll_tax_benefits_pct"],
          },
        },
        "capacity_labor_model": {"type": "string", "enum": ["labor_driven", "hybrid", "system_driven", "expert_driven"]},
        "labor_intensity_class": {"type": "string", "enum": ["low", "medium", "high", "expert"]},
        "wage_positioning_tier": {"type": "string", "enum": ["floor", "market", "premium", "specialized"]},
        "wage_positioning_multiplier": {"type": "number", "minimum": 1.0, "maximum": 3.0},
        "capacity_units_per_supporting_fte": {"type": "number", "minimum": 0.0001},
        "target_payroll_percent_of_revenue": {"type": "number", "minimum": 0.06, "maximum": 0.80},
        "revenue_scales_with_labor": {
          "type": "boolean",
          "description": (
            "YOUR JUDGMENT for THIS business: does growing revenue REQUIRE adding "
            "staff roughly in proportion? true = labor-bound (a dental practice, "
            "restaurant, salon, clinic, agency: more patients/covers/clients need "
            "more hygienists/servers/stylists/staff, so payroll must GROW with "
            "revenue and payroll%-of-revenue stays ~flat). false = genuine "
            "operating leverage (software, licensing, rentals, franchising: revenue "
            "can multiply on a ~fixed team, so payroll%-of-revenue falls as you "
            "scale). Ground this in what the business actually does -- do not "
            "default to true; some businesses genuinely have leverage."
          ),
        },
        "labor_scaling_rationale": {
          "type": "string",
          "description": "One sentence: why this business is labor-bound or has operating leverage.",
        },
        "rationale": {"type": "string"},
      },
      "required": [
        "payroll_headcount_grid", "capacity_labor_model", "labor_intensity_class",
        "wage_positioning_tier", "wage_positioning_multiplier",
        "capacity_units_per_supporting_fte", "target_payroll_percent_of_revenue",
        "revenue_scales_with_labor", "labor_scaling_rationale", "rationale",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the executive authoring the round-1 payroll headcount schedule for a "
  "post-intake business plan. Python has computed a revenue-grounded payroll ANCHOR "
  "(per-quarter payroll budget and the supporting FTE it implies) and the NAICS OEWS "
  "title catalog. YOU decide which OEWS occupation titles to staff and the ending FTE "
  "per title per quarter, grounded in that anchor. Python validates your contract and "
  "derives the mechanical fields. Rules you MUST follow:\n"
  "1. Use ONLY exact occ_title strings from the supplied oews_title_catalog.\n"
  "2. For each title you staff, provide a row for EVERY quarter Q1..Q20. Once a title "
  "starts it stays active through Q20.\n"
  "3. ending_fte is your staffing decision. It MUST be NON-DECREASING across quarters "
  "for a given title (you may hold flat or grow; you may NOT reduce a title's FTE). "
  "Set starting_fte=0 and hires=0 on every row -- Python derives them from continuity.\n"
  "4. Staff so each quarter's TOTAL supporting payroll tracks the anchor's "
  "supporting_budget: total ending FTE across titles each quarter should be close to "
  "that quarter's implied_supporting_fte_total, distributed across titles roughly by "
  "the suggested mix weights. Do not overstaff beyond the budget or understaff to zero "
  "when budget exists.\n"
  "5. payroll_tax_benefits_pct must be within [0.12, 0.35]; use the anchor benefits_pct "
  "unless you have reason to differ.\n"
  "6. Set the root scalars from the anchor (labor_intensity_class, capacity_labor_model, "
  "wage_positioning_tier, wage_positioning_multiplier, target_payroll_percent_of_revenue) "
  "unless business judgment dictates an in-band adjustment.\n"
  "7. JUDGE the labor model for THIS business and set revenue_scales_with_labor. A "
  "labor-bound business (dental, restaurant, salon, clinic, agency) must ADD staff as "
  "revenue grows -- more patients/covers/clients need more hygienists/servers/stylists -- "
  "so its payroll grows with revenue and payroll%-of-revenue stays roughly flat; staff "
  "the per-quarter grid so total ending FTE RISES with the anchor's per-quarter revenue "
  "(do NOT hold headcount flat while revenue doubles). A leverage business (software, "
  "licensing, rentals) can grow revenue on a ~fixed team; payroll%-of-revenue falls. "
  "Ground the judgment in what the business does; do not default to either. Judge from "
  "what the business DOES at the point of sale (the BUSINESS IDENTITY block), NOT from "
  "the OEWS occupation list -- the occupation mix can be manufacturing-flavored even for "
  "a walk-in counter shop.\n"
  "Call submit_payroll_headcount_schedule exactly once with the complete contract."
)


def _build_user_prompt(
  *,
  anchor: Dict[str, Any],
  oews_catalog: Dict[str, Any],
  previous_violations: Optional[List[Dict[str, Any]]],
  business_identity: Optional[Dict[str, Any]] = None,
) -> str:
  candidates = [
    {
      "occ_title": str(c.get("occ_title") or "").strip(),
      "tot_emp": c.get("tot_emp"),
      "annual_wage": c.get("annual_wage"),
      "o_group": c.get("o_group"),
    }
    for c in (oews_catalog.get("title_candidates") or [])
    if isinstance(c, dict) and str(c.get("occ_title") or "").strip()
  ]
  # Keep the catalog bounded so the prompt stays in budget; the anchor's
  # suggested_oews_mix already surfaces the highest-employment titles.
  candidates = candidates[:60]
  lines: List[str] = []
  # BUSINESS IDENTITY comes FIRST (context before numbers). Without it the
  # labor-model judgment is made blind, and the only identity-flavored signal
  # left -- the OEWS occupation mix -- can be manufacturing-flavored even for a
  # walk-in counter shop (NAICS 311811 "Retail Bakeries" lists Food
  # Batchmakers / Packers / Industrial Machinery Mechanics), which flipped an
  # obviously labor-bound donut shop to "leverage". A ~60-token block, not the
  # full compact: just what the business IS.
  if isinstance(business_identity, dict) and any(business_identity.values()):
    lines.append(
      "BUSINESS IDENTITY (what this business IS -- judge revenue_scales_with_labor from this):"
    )
    lines.append(json.dumps(
      {k: v for k, v in business_identity.items() if v},
      ensure_ascii=False, default=str,
    ))
    lines.append("")
  lines.append("PAYROLL ANCHOR (revenue-grounded reference; non-binding):")
  lines.append(json.dumps({
    "horizon": anchor.get("horizon"),
    "labor_intensity_class": anchor.get("labor_intensity_class"),
    "target_payroll_percent_of_revenue": anchor.get("target_payroll_percent_of_revenue"),
    "benefits_pct": anchor.get("benefits_pct"),
    "capacity_labor_model": anchor.get("capacity_labor_model"),
    "wage_positioning_tier": anchor.get("wage_positioning_tier"),
    "wage_positioning_multiplier": anchor.get("wage_positioning_multiplier"),
    "payroll_revenue_band": anchor.get("payroll_revenue_band"),
    "suggested_oews_mix": anchor.get("suggested_oews_mix"),
    "per_quarter": anchor.get("per_quarter"),
  }, ensure_ascii=False, default=str))
  lines.append("")
  lines.append("OEWS TITLE CATALOG (choose oews_occ_title strings ONLY from here):")
  lines.append(json.dumps(candidates, ensure_ascii=False, default=str))
  if previous_violations:
    lines.append("")
    lines.append(
      "YOUR PREVIOUS CONTRACT WAS REJECTED by Python validation. Fix exactly "
      "these problems and resubmit the FULL corrected contract:"
    )
    lines.append(json.dumps(previous_violations[:20], ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_payroll_contract_once(
  *,
  anchor: Dict[str, Any],
  oews_catalog: Dict[str, Any],
  previous_violations: Optional[List[Dict[str, Any]]] = None,
  business_identity: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 1729,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE GPT authoring call; return ``{ok, contract, error}``.

  ``ok=False`` on missing key / HTTP error / malformed tool call. The
  caller validates the returned contract and decides whether to retry
  (feeding ``previous_violations`` back) or fall back.
  """
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "contract": None, "error": "openai_api_key_unset"}

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
        anchor=anchor, oews_catalog=oews_catalog,
        previous_violations=previous_violations,
        business_identity=business_identity,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_payroll_headcount_schedule"}},
    "seed": int(seed),
  }
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  try:
    resp = http_fn(
      url=_OPENAI_URL, headers=headers, payload=payload,
      timeout_seconds=timeout_seconds,
      retryable_status=(429, 500, 502, 503, 504), max_attempts=3,
    )
  except Exception as exc:
    return {"ok": False, "contract": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    detail = str(getattr(resp, "text", ""))[:300]
    return {"ok": False, "contract": None, "error": f"http_status_{status}:{detail}"}
  try:
    body = resp.json()
  except Exception:
    return {"ok": False, "contract": None, "error": "non_json_body"}

  try:
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    contract = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "contract": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(contract, dict) or not contract.get("payroll_headcount_grid"):
    return {"ok": False, "contract": None, "error": "no_contract_in_tool_call"}
  # The labor-model judgment rides in the RETURN ENVELOPE, not the validated
  # contract: the payroll contract table is strict and would reject unknown
  # fields. Pop it off the contract so the validator sees only its known shape;
  # the caller (set_payroll_schedule) enforces payroll scaling from the envelope.
  revenue_scales = contract.pop("revenue_scales_with_labor", None)
  labor_scaling_rationale = contract.pop("labor_scaling_rationale", None)
  return {
    "ok": True,
    "contract": contract,
    "error": None,
    "revenue_scales_with_labor": (
      bool(revenue_scales) if isinstance(revenue_scales, bool) else None
    ),
    "labor_scaling_rationale": (
      str(labor_scaling_rationale) if labor_scaling_rationale else None
    ),
  }


__all__ = ["gpt_author_payroll_contract_once"]
