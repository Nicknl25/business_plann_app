"""RESTRUCTURE CONSTRAINT AUTHOR — GPT authors the FEASIBLE REGION.

In restructure v2 the executive does not propose lever values. It
authors the FOUR REALITY CONSTRAINTS as actual BOUNDS on the whole
P&L configuration space:

  - REAL MARKET  -> price ceilings per line, volume caps per line,
                    revenue caps for any added line (customers who
                    actually exist, prices they actually pay).
  - REAL PHYSICS -> the team-payroll FLOOR the output genuinely needs,
                    the space floor, the COGS floor the product's
                    physics allows.
  - STILL THIS BUSINESS -> which lines may be dropped, what may be
                    added (only things THIS founder's operation can
                    really produce and sell).
  - LENDER-DEFENSIBLE -> the executive's overall region attestation.

The deterministic searcher then explores EVERY configuration inside
those bounds (fast evaluator scores; the real pipeline issues the
final verdict). GPT judges what is REAL; the machine does the math.

The honest terminal stays: ``feasible_region_exists=false`` means the
executive concludes no real configuration region exists (a genuinely
doomed business — the Glaze answer).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from client_intake_and_finmo.post_intake_restructure.designer import (  # type: ignore
  OWNER_TITLE_TOKENS,  # noqa: F401 — re-exported surface
  stated_owner_annual_wage,  # noqa: F401
)

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 90.0

# Machine sanity rails on the BOUNDS themselves (arithmetic coherence,
# not viability ceilings): no bound may leave these outer envelopes.
BOUNDS_RAILS: Dict[str, Any] = {
  "price_multiplier_max": (1.00, 3.00),
  "volume_multiplier_max": (1.00, 4.00),
  "new_line_gross_margin": (0.05, 0.95),
  "cost_pct": (0.005, 0.95),
  "annual_growth_max": (0.00, 1.00),
  "max_new_line_candidates": 3,
}


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


def _num(value: Any) -> Optional[float]:
  try:
    v = float(value)
    return v if v == v else None
  except (TypeError, ValueError):
    return None


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_restructure_bounds",
    "description": (
      "Submit the feasible-region BOUNDS for restructuring this "
      "business (or conclude no real feasible region exists). Call "
      "exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "feasible_region_exists": {
          "type": "boolean",
          "description": (
            "false ONLY when no realistic configuration region exists "
            "at all — the stated market cannot support any viable "
            "arrangement of this business (then all other fields are "
            "ignored)."
          ),
        },
        "existing_lines": {
          "type": "array",
          "description": (
            "One entry PER existing revenue line (identified by the "
            "lob/product names in CURRENT STRUCTURE)."
          ),
          "items": {
            "type": "object",
            "properties": {
              "lob": {"type": "string"},
              "product": {"type": "string"},
              "price_multiplier_max": {
                "type": "number",
                "description": (
                  "The HIGHEST price multiple of the current authored "
                  "price this line's real customers demonstrably pay "
                  "(1.0 = no headroom)."
                ),
              },
              "volume_multiplier_max": {
                "type": "number",
                "description": (
                  "The HIGHEST volume multiple the real market demand "
                  "AND the operation's physics support by ~year 3."
                ),
              },
              "can_drop": {
                "type": "boolean",
                "description": (
                  "true if winding this line down entirely would still "
                  "be THIS business."
                ),
              },
              "gross_margin_pct": {
                "type": "number",
                "description": (
                  "THIS line's true unit gross margin (0-1 fraction: "
                  "price minus its own direct costs, over price). The "
                  "solver reasons about MIX with these — a blended "
                  "average hides exactly the signal a mix restructure "
                  "needs. Estimate honestly per line."
                ),
              },
              "rationale": {"type": "string"},
            },
            "required": [
              "lob", "product", "price_multiplier_max",
              "volume_multiplier_max", "can_drop", "gross_margin_pct",
              "rationale",
            ],
          },
        },
        "new_line_candidates": {
          "type": "array",
          "description": (
            "REAL additions this operation can genuinely produce and "
            "this market genuinely buys (value-added product, channel, "
            "tier). Empty array if none are real."
          ),
          "items": {
            "type": "object",
            "properties": {
              "lob": {"type": "string"},
              "product": {"type": "string"},
              "unit_price": {"type": "number"},
              "q11_quarterly_revenue_max": {
                "type": "number",
                "description": (
                  "The MOST quarterly revenue this line realistically "
                  "does by ~year 3 (the market cap, not a target)."
                ),
              },
              "gross_margin_pct": {"type": "number"},
              "rationale": {"type": "string"},
            },
            "required": [
              "lob", "product", "unit_price",
              "q11_quarterly_revenue_max", "gross_margin_pct", "rationale",
            ],
          },
        },
        "team": {
          "type": "object",
          "properties": {
            "min_annual_payroll": {
              "type": "number",
              "description": (
                "REAL PHYSICS floor: the smallest total annual payroll "
                "(owner included) that can actually produce the output "
                "of a restructured plan at roughly current scale. "
                "Cutting below this is understaffing, not efficiency."
              ),
            },
            "max_annual_payroll": {"type": "number"},
            "structure_at_min": {"type": "string"},
            "rationale": {"type": "string"},
          },
          "required": [
            "min_annual_payroll", "max_annual_payroll",
            "structure_at_min", "rationale",
          ],
        },
        "facility": {
          "type": "object",
          "properties": {
            "min_quarterly_rent": {
              "type": "number",
              "description": (
                "The smallest quarterly rent for space this operation "
                "physically fits in (REAL PHYSICS floor)."
              ),
            },
            "max_quarterly_rent": {"type": "number"},
            "rationale": {"type": "string"},
          },
          "required": ["min_quarterly_rent", "max_quarterly_rent", "rationale"],
        },
        "cost_floors": {
          "type": "object",
          "description": (
            "Percent-of-revenue FLOORS the physics of this business "
            "allows (fractions 0-1): the product cannot be made for "
            "less COGS, the operation cannot run on less G&A, the "
            "channel cannot sell on less marketing."
          ),
          "properties": {
            "cogs_percent_of_revenue_min": {"type": "number"},
            "marketing_percent_of_revenue_min": {"type": "number"},
            "g_and_a_percent_of_revenue_min": {"type": "number"},
            "rationale": {"type": "string"},
          },
          "required": [
            "cogs_percent_of_revenue_min",
            "marketing_percent_of_revenue_min",
            "g_and_a_percent_of_revenue_min", "rationale",
          ],
        },
        "growth": {
          "type": "object",
          "properties": {
            "year1_annual_growth_max": {"type": "number"},
            "mature_annual_growth_max": {"type": "number"},
            "rationale": {"type": "string"},
          },
          "required": [
            "year1_annual_growth_max", "mature_annual_growth_max", "rationale",
          ],
        },
        "overall_rationale": {"type": "string"},
        "reality_constraints": {
          "type": "object",
          "description": "Per-constraint attestation — HOW the bounds encode each.",
          "properties": {
            "real_market": {"type": "string"},
            "real_physics": {"type": "string"},
            "still_this_business": {"type": "string"},
            "lender_defensible": {"type": "string"},
          },
          "required": [
            "real_market", "real_physics",
            "still_this_business", "lender_defensible",
          ],
        },
      },
      "required": [
        "feasible_region_exists", "existing_lines", "new_line_candidates",
        "team", "facility", "cost_floors", "growth",
        "overall_rationale", "reality_constraints",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER acting as a turnaround consultant. The "
  "normal planning process could not make this business work as "
  "currently structured. A deterministic solver is about to search EVERY "
  "configuration of this business — every mix reallocation, price "
  "level, added or dropped line, team size, facility, cost shape, "
  "growth path — for a viable design. YOUR job is to author the FENCE "
  "the search must stay inside: the FOUR REALITY CONSTRAINTS, expressed "
  "as hard bounds.\n"
  "1. REAL MARKET — price ceilings this line's customers demonstrably "
  "pay; volume caps the demand actually supports; revenue caps for any "
  "added line. The solver will push TO your ceilings — set them where "
  "reality is, not where viability needs them.\n"
  "2. REAL PHYSICS — the payroll FLOOR the output genuinely needs "
  "(below it is understaffing, not efficiency); the space floor the "
  "operation fits in; the COGS floor the product can actually be made "
  "for.\n"
  "3. STILL THIS BUSINESS — which lines may be dropped and still be "
  "this founder's venture; only additions this operation can genuinely "
  "produce and this market genuinely buys.\n"
  "4. LENDER-DEFENSIBLE — the whole region must be one a lender reads "
  "as real. If a bound embarrasses you in front of an underwriter, "
  "tighten it.\n"
  "Be neither timid nor fantastical: a turnaround consultant knows "
  "specialty pricing headroom, real value-added opportunities, and real "
  "demand limits. Bounds too tight starve the search of real options; "
  "bounds too loose let it design a fantasy — both are failures.\n"
  "IF NO REAL REGION EXISTS — the stated market is simply too small for "
  "ANY arrangement — say so plainly with feasible_region_exists=false. "
  "That is a valid, honest answer.\n"
  "Call submit_restructure_bounds exactly once."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  stated_facts: Dict[str, Any],
  current_structure: Dict[str, Any],
  failure_summary: Optional[Dict[str, Any]] = None,
) -> str:
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
    MARKET_SEMANTICS_PRIMER,
  )
  _compact = dict(compact or {})
  market_reality = {
    k: _compact.pop(k) for k in ("target_market", "market_demand") if k in _compact
  }
  lines: List[str] = []
  lines.append("BUSINESS COMPACT (what this business IS):")
  lines.append(json.dumps(_compact, ensure_ascii=False, default=str))
  lines.append("")
  if market_reality:
    lines.append(
      "MARKET REALITY (constraint 1 lives here — demand and price "
      "tolerance your bounds may not exceed):"
    )
    lines.append(json.dumps(market_reality, ensure_ascii=False, default=str))
    lines.append("")
    lines.append(MARKET_SEMANTICS_PRIMER)
    lines.append("")
  lines.append("STATED FACTS (the operator's present-day reality):")
  lines.append(json.dumps(stated_facts, ensure_ascii=False, default=str))
  lines.append("")
  lines.append(
    "CURRENT STRUCTURE (the shape that did not work — per-line revenue "
    "included; your existing_lines entries must use these lob/product "
    "names):"
  )
  lines.append(json.dumps(current_structure, ensure_ascii=False, default=str))
  if failure_summary:
    lines.append("")
    lines.append(
      "WHY THE AS-STATED PLAN FAILED (the solver's landing — context "
      "for how far reality must stretch, NOT a target to design to):"
    )
    lines.append(json.dumps(failure_summary, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_restructure_bounds_once(
  *,
  compact: Dict[str, Any],
  stated_facts: Dict[str, Any],
  current_structure: Dict[str, Any],
  failure_summary: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 2741,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """ONE bounds-authoring call (locked). Returns ``{ok, bounds, error}``
  (RAW — pass through ``validate_restructure_bounds``)."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "bounds": None, "error": "openai_api_key_unset"}
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
        compact=compact, stated_facts=stated_facts,
        current_structure=current_structure,
        failure_summary=failure_summary,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_restructure_bounds"}},
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
    return {"ok": False, "bounds": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}
  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "bounds": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "bounds": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}
  if not isinstance(parsed, dict) or "feasible_region_exists" not in parsed:
    return {"ok": False, "bounds": None, "error": "no_bounds_in_tool_call"}
  return {"ok": True, "bounds": parsed, "error": None}


def validate_restructure_bounds(
  *,
  bounds: Dict[str, Any],
  stated_owner_annual_wage: float,
) -> Dict[str, Any]:
  """Rail the raw bounds into an executable search region (arithmetic
  coherence only — the bounds themselves ARE the reality fence)."""
  notes: List[str] = []
  b = bounds or {}
  feasible = bool(b.get("feasible_region_exists"))
  rc = b.get("reality_constraints") if isinstance(b.get("reality_constraints"), dict) else {}
  attestations = {
    k: str(rc.get(k) or "").strip()
    for k in ("real_market", "real_physics", "still_this_business", "lender_defensible")
  }
  if feasible and not all(attestations.values()):
    feasible = False
    notes.append("bounds_rejected_missing_reality_attestations")

  p_lo, p_hi = BOUNDS_RAILS["price_multiplier_max"]
  v_lo, v_hi = BOUNDS_RAILS["volume_multiplier_max"]
  c_lo, c_hi = BOUNDS_RAILS["cost_pct"]
  g_lo, g_hi = BOUNDS_RAILS["annual_growth_max"]
  m_lo, m_hi = BOUNDS_RAILS["new_line_gross_margin"]

  def _clamp(value: Any, lo: float, hi: float, name: str, fallback: float) -> float:
    v = _num(value)
    if v is None:
      notes.append(f"{name}_missing_default_{fallback}")
      return float(fallback)
    c = min(max(float(v), lo), hi)
    if abs(c - float(v)) > 1e-9:
      notes.append(f"{name}_clamped_{float(v):.4f}->{c:.4f}")
    return c

  existing_lines: List[Dict[str, Any]] = []
  for entry in (b.get("existing_lines") or []):
    if not isinstance(entry, dict):
      continue
    lob = str(entry.get("lob") or "").strip()
    product = str(entry.get("product") or "").strip()
    if not (lob or product):
      notes.append("bounds_line_skipped_no_identity")
      continue
    _margin_raw = _num(entry.get("gross_margin_pct"))
    existing_lines.append({
      "lob": lob[:120],
      "product": product[:120],
      "price_multiplier_max": _clamp(entry.get("price_multiplier_max"), p_lo, p_hi, f"pmax_{product or lob}", 1.0),
      "volume_multiplier_max": _clamp(entry.get("volume_multiplier_max"), v_lo, v_hi, f"vmax_{product or lob}", 1.0),
      "can_drop": bool(entry.get("can_drop")),
      "gross_margin_pct": (
        _clamp(_margin_raw, m_lo, m_hi, f"margin_{product or lob}", 0.50)
        if _margin_raw is not None else None
      ),
      "rationale": str(entry.get("rationale") or "")[:400],
    })

  new_line_candidates: List[Dict[str, Any]] = []
  for entry in (b.get("new_line_candidates") or [])[: int(BOUNDS_RAILS["max_new_line_candidates"])]:
    if not isinstance(entry, dict):
      continue
    lob = str(entry.get("lob") or "").strip()
    product = str(entry.get("product") or "").strip()
    unit_price = _num(entry.get("unit_price"))
    rev_max = _num(entry.get("q11_quarterly_revenue_max"))
    if not (lob or product) or unit_price is None or unit_price <= 0 or rev_max is None or rev_max <= 0:
      notes.append("bounds_new_line_skipped_incomplete")
      continue
    new_line_candidates.append({
      "lob": lob[:120] or "New",
      "product": product[:120] or "New Line",
      "unit_price": round(float(unit_price), 2),
      "q11_quarterly_revenue_max": round(float(rev_max), 2),
      "gross_margin_pct": _clamp(entry.get("gross_margin_pct"), m_lo, m_hi, f"nl_margin_{product or lob}", 0.50),
      "rationale": str(entry.get("rationale") or "")[:400],
    })

  team = b.get("team") if isinstance(b.get("team"), dict) else {}
  owner_wage = max(0.0, float(stated_owner_annual_wage or 0.0))
  team_min = _num(team.get("min_annual_payroll"))
  team_max = _num(team.get("max_annual_payroll"))
  if team_min is None or team_min <= 0:
    feasible = False
    notes.append("bounds_rejected_no_team_floor")
    team_min = 0.0
  elif owner_wage > 0 and team_min < owner_wage:
    notes.append(f"team_floor_raised_to_owner_wage_{team_min:.0f}->{owner_wage:.0f}")
    team_min = owner_wage
  team_max_v = max(float(team_min or 0.0), float(team_max or 0.0))

  facility = b.get("facility") if isinstance(b.get("facility"), dict) else {}
  rent_min = max(0.0, float(_num(facility.get("min_quarterly_rent")) or 0.0))
  rent_max = max(rent_min, float(_num(facility.get("max_quarterly_rent")) or rent_min))

  cost = b.get("cost_floors") if isinstance(b.get("cost_floors"), dict) else {}
  cost_floors = {
    key: _clamp(cost.get(key), c_lo, c_hi, f"floor_{key}", c_lo)
    for key in (
      "cogs_percent_of_revenue_min",
      "marketing_percent_of_revenue_min",
      "g_and_a_percent_of_revenue_min",
    )
  }

  growth = b.get("growth") if isinstance(b.get("growth"), dict) else {}

  return {
    "feasible_region_exists": feasible,
    "existing_lines": existing_lines,
    "new_line_candidates": new_line_candidates,
    "team": {
      "min_annual_payroll": round(float(team_min), 2),
      "max_annual_payroll": round(team_max_v, 2),
      "structure_at_min": str(team.get("structure_at_min") or "")[:300],
      "rationale": str(team.get("rationale") or "")[:500],
    },
    "facility": {
      "min_quarterly_rent": round(rent_min, 2),
      "max_quarterly_rent": round(rent_max, 2),
      "rationale": str(facility.get("rationale") or "")[:500],
    },
    "cost_floors": {**cost_floors, "rationale": str(cost.get("rationale") or "")[:500]},
    "growth": {
      "year1_annual_growth_max": _clamp(growth.get("year1_annual_growth_max"), g_lo, g_hi, "growth_y1_max", 0.15),
      "mature_annual_growth_max": _clamp(growth.get("mature_annual_growth_max"), g_lo, g_hi, "growth_mature_max", 0.05),
      "rationale": str(growth.get("rationale") or "")[:500],
    },
    "overall_rationale": str(b.get("overall_rationale") or "")[:900],
    "reality_constraints": attestations,
    "notes": notes,
  }


__all__ = [
  "gpt_author_restructure_bounds_once",
  "validate_restructure_bounds",
  "BOUNDS_RAILS",
]
