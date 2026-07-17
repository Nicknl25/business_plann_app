"""THE RESTRUCTURE STAGE — the executive redesigns the whole business.

A new FINAL stage that fires ONLY when the full existing process returns
NON-VIABLE. Everything the system does today runs first, exactly as-is;
a viable business never enters this stage and is untouched.

THE DIVISION OF LABOR (the same separation as every judgment in the app,
and itself part of the fence):
  - The EXECUTIVE makes DESIGN DECISIONS: what the restructured business
    looks like — headcount, space, product mix, pricing, phasing — the
    operator/turnaround-consultant choices, reasoned qualitatively as
    "is this a REAL, defensible business."
  - The SOLVER (the entire existing pipeline) CRUNCHES: it takes the
    design, rebuilds the whole plan (authoring, bands, WC, cash,
    acceptance), and reports back the verdict and the gap.
  - They LOOP: design -> solve -> gap report -> redesign (realistically,
    informed by the numbers) -> solve ... until viable, or until the
    executive concludes NO real redesign reaches viability.
  The executive never crunches the P&L and never picks numbers-to-pass;
  it decides realistic restructurings and the solver tells it whether
  they pencil. That seat separation keeps it out of the fake-viable
  frame.

THE ONLY FENCE — the FOUR REALITY CONSTRAINTS (these replace every
per-lever ceiling in restructure mode; total freedom to redesign WITHIN
reality, and reality is airtight):
  1. REAL MARKET  — customers actually pay these prices at these volumes.
  2. REAL PHYSICS — labor/capacity/space can actually produce the output.
  3. STILL THIS BUSINESS — a realistic version of what THIS founder is
     building, not a pivot to a different company.
  4. LENDER-DEFENSIBLE — a lender reads the restructured plan and
     believes it is a real, fundable business.
A genuinely doomed business fails one of the four by construction (you
cannot invent customers), which is why unlimited levers stay honest.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 90.0

# Machine sanity rails on the DESIGN (not viability ceilings — just
# physical/arithmetic coherence bounds on the directive itself).
RESTRUCTURE_RAILS: Dict[str, Any] = {
  "price_multiplier": (0.50, 3.00),
  "annual_growth": (-0.20, 1.00),
  "volume_multiplier": (0.00, 4.00),
  "cost_percent_of_revenue": (0.01, 0.95),
  "new_line_gross_margin": (0.05, 0.95),
  "max_new_lines": 3,
  "max_design_iterations": 3,
}

OWNER_TITLE_TOKENS = ("owner", "founder", "principal", "proprietor", "member")


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
    "name": "submit_restructure_design",
    "description": (
      "Submit the restructured business design (or conclude that no real "
      "redesign reaches a fundable business). Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "restructure_feasible": {
          "type": "boolean",
          "description": (
            "false ONLY when NO realistic redesign of this business "
            "satisfies all four reality constraints as a fundable "
            "business (e.g. the stated market demand is simply too small "
            "to support any viable arrangement). When false, the other "
            "design fields are ignored."
          ),
        },
        "team": {
          "type": "object",
          "properties": {
            "annual_payroll": {
              "type": "number",
              "description": (
                "Total annual payroll (owner included) of the "
                "restructured team."
              ),
            },
            "structure": {"type": "string", "description": "The team in plain words."},
            "rationale": {"type": "string"},
          },
          "required": ["annual_payroll", "structure", "rationale"],
        },
        "pricing": {
          "type": "object",
          "properties": {
            "price_multiplier_q11": {
              "type": "number",
              "description": (
                "Restructured price level by ~year 3 as a MULTIPLIER on "
                "the current plan's authored price path (1.0 = keep; "
                "1.3 = 30% above the authored trajectory). Must be a "
                "price the REAL MARKET pays at the assumed volumes."
              ),
            },
            "price_multiplier_q20": {"type": "number"},
            "rationale": {"type": "string"},
          },
          "required": ["price_multiplier_q11", "price_multiplier_q20", "rationale"],
        },
        "facility": {
          "type": "object",
          "properties": {
            "quarterly_rent_target": {
              "type": "number",
              "description": (
                "Restructured QUARTERLY facility rent once the redesign "
                "is executed (real space the operation fits in)."
              ),
            },
            "rationale": {"type": "string"},
          },
          "required": ["quarterly_rent_target", "rationale"],
        },
        "growth": {
          "type": "object",
          "properties": {
            "year1_annual_growth": {"type": "number"},
            "mature_annual_growth": {"type": "number"},
            "rationale": {"type": "string"},
          },
          "required": ["year1_annual_growth", "mature_annual_growth", "rationale"],
        },
        "revenue_mix": {
          "type": "object",
          "description": (
            "THE REVENUE-SIDE RESTRUCTURE — usually where viability "
            "lives. Reallocate volume across existing lines (emphasize "
            "the earners, shrink or drop the money-losers) and add the "
            "real higher-margin lines a turnaround operator would add."
          ),
          "properties": {
            "lines": {
              "type": "array",
              "description": (
                "One entry PER EXISTING revenue line you are changing "
                "(omit lines you keep as-is). Identify each by the "
                "lob/product names shown in CURRENT STRUCTURE."
              ),
              "items": {
                "type": "object",
                "properties": {
                  "lob": {"type": "string"},
                  "product": {"type": "string"},
                  "volume_multiplier_q11": {
                    "type": "number",
                    "description": (
                      "Restructured VOLUME of this line by ~year 3 as a "
                      "multiplier on the current plan's volume path "
                      "(1.0 = keep; 2.0 = double down; 0.0 = drop the "
                      "line entirely, wound down by Q11)."
                    ),
                  },
                  "volume_multiplier_q20": {"type": "number"},
                  "rationale": {"type": "string"},
                },
                "required": [
                  "lob", "product", "volume_multiplier_q11",
                  "volume_multiplier_q20", "rationale",
                ],
              },
            },
            "new_lines": {
              "type": "array",
              "description": (
                "Real NEW revenue lines the restructured business adds "
                "(a value-added product, a wholesale channel, a service "
                "tier). Each must be something THIS business can "
                "actually produce and THIS market actually buys."
              ),
              "items": {
                "type": "object",
                "properties": {
                  "lob": {"type": "string"},
                  "product": {"type": "string"},
                  "unit_price": {"type": "number"},
                  "q11_quarterly_revenue_target": {
                    "type": "number",
                    "description": (
                      "Quarterly revenue this line realistically does "
                      "by ~year 3, ramped from zero (Q1 stays stated "
                      "reality)."
                    ),
                  },
                  "gross_margin_pct": {
                    "type": "number",
                    "description": "Unit gross margin, 0-1 fraction.",
                  },
                  "rationale": {"type": "string"},
                },
                "required": [
                  "lob", "product", "unit_price",
                  "q11_quarterly_revenue_target", "gross_margin_pct",
                  "rationale",
                ],
              },
            },
          },
          "required": ["lines", "new_lines"],
        },
        "cost_structure": {
          "type": "object",
          "description": (
            "The FULL restructured cost shape as percent-of-revenue "
            "targets at maturity (fractions 0-1). Set the ones your "
            "redesign changes; null/omit to keep a category as-is. "
            "COGS is where a margin-improving mix shift lands: selling "
            "more 55%-margin product means a LOWER blended COGS ratio."
          ),
          "properties": {
            "cogs_percent_of_revenue": {"type": ["number", "null"]},
            "marketing_percent_of_revenue": {"type": ["number", "null"]},
            "g_and_a_percent_of_revenue": {"type": ["number", "null"]},
            "rationale": {"type": "string"},
          },
          "required": ["rationale"],
        },
        "product_mix_notes": {
          "type": "string",
          "description": (
            "What the restructured business sells and emphasizes (mix "
            "shifts toward higher-margin lines, dropped offerings, etc.)."
          ),
        },
        "overall_rationale": {
          "type": "string",
          "description": (
            "The turnaround story a lender reads: what changes, why the "
            "restructured version is a real business (4-6 sentences)."
          ),
        },
        "reality_constraints": {
          "type": "object",
          "description": "Per-constraint attestation — HOW the design satisfies each.",
          "properties": {
            "real_market": {"type": "string"},
            "real_physics": {"type": "string"},
            "still_this_business": {"type": "string"},
            "lender_defensible": {"type": "string"},
          },
          "required": ["real_market", "real_physics", "still_this_business", "lender_defensible"],
        },
      },
      "required": [
        "restructure_feasible", "team", "pricing", "facility", "growth",
        "revenue_mix", "cost_structure", "product_mix_notes",
        "overall_rationale", "reality_constraints",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER acting as a turnaround consultant: the "
  "normal planning process could not make this business work as "
  "currently structured, and you are asked to REDESIGN THE BUSINESS "
  "ITSELF into the version a real operator would actually run — "
  "headcount and team shape, facility and space, product mix, pricing, "
  "growth phasing. You make DESIGN decisions; a deterministic solver "
  "will crunch every number and report back. Never pick numbers to make "
  "math pass — design the REAL business, and let the solver tell us "
  "whether it pencils.\n"
  "YOU HAVE NO PER-LEVER LIMITS. Move anything, as far as needed, "
  "together. The ONLY fence is the FOUR REALITY CONSTRAINTS, and every "
  "element of your design must satisfy ALL FOUR:\n"
  "1. REAL MARKET — customers will actually pay the prices at the "
  "volumes assumed. No fantasy pricing or invented demand.\n"
  "2. REAL PHYSICS — the labor, capacity, and space in your design can "
  "actually produce the output. No one-person miracles, no output "
  "beyond what the equipment and hours allow.\n"
  "3. STILL THIS BUSINESS — a realistic version of what THIS founder is "
  "building, not a pivot to a different company.\n"
  "4. LENDER-DEFENSIBLE — a lender reads the restructured plan and "
  "believes it is a real, fundable business.\n"
  "HOW A TURNAROUND CONSULTANT DESIGNS — REVENUE STRUCTURE FIRST: cost "
  "cuts alone almost never save a business whose problem is what it "
  "sells and what that earns. Your most powerful levers are the "
  "REVENUE-SIDE STRUCTURAL MOVES, and you have all of them:\n"
  "- REALLOCATE THE MIX (revenue_mix.lines): shift volume toward the "
  "lines that earn and away from the ones that don't — double down on "
  "the 55%-margin value-added line, shrink the low-margin commodity "
  "line, DROP a money-loser outright (volume multiplier 0).\n"
  "- ADD REAL LINES (revenue_mix.new_lines): the higher-margin product, "
  "channel, or tier a real operator in this position would add — one "
  "this business can actually produce and this market actually buys.\n"
  "- RESHAPE THE FULL COST STRUCTURE (cost_structure): the blended COGS "
  "ratio of the NEW mix, the marketing spend the NEW channel needs, the "
  "G&A a leaner operation carries — not just rent and payroll.\n"
  "Then complete the redesign around it: resize the team to the output; "
  "fit the space to the operation; price what the product is worth to "
  "the customers who actually buy it; phase growth the way the rebuilt "
  "operation can deliver. Cutting an overstaffed team to what the "
  "output needs is honest; cutting below what the output needs is fake "
  "(REAL PHYSICS kills it). Raising prices to what the market "
  "demonstrably bears is honest; pricing past the customer is fake "
  "(REAL MARKET kills it). Adding a line the operation can genuinely "
  "produce and sell is honest; inventing demand is fake (REAL MARKET "
  "kills it).\n"
  "IF NO REAL REDESIGN EXISTS — if the stated market is simply too "
  "small, or every arrangement that satisfies the four constraints "
  "still cannot be a fundable business — say so plainly with "
  "restructure_feasible=false. That is a valid, honest answer.\n"
  "When a SOLVER GAP REPORT from your previous design is provided, use "
  "it as your calculator's feedback: understand WHERE the last design "
  "fell short and REDESIGN realistically — do not shave numbers to "
  "cover a gap; change the design.\n"
  "Call submit_restructure_design exactly once."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  stated_facts: Dict[str, Any],
  current_structure: Dict[str, Any],
  prior_design: Optional[Dict[str, Any]] = None,
  solver_gap_report: Optional[Dict[str, Any]] = None,
) -> str:
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
    MARKET_SEMANTICS_PRIMER,
  )
  _compact = dict(compact or {})
  market_reality = {
    k: _compact.pop(k) for k in ("target_market", "market_demand") if k in _compact
  }
  lines: List[str] = []
  lines.append("BUSINESS COMPACT (what this business IS — the founder's venture you are restructuring):")
  lines.append(json.dumps(_compact, ensure_ascii=False, default=str))
  lines.append("")
  if market_reality:
    lines.append(
      "MARKET REALITY (constraint 1 lives here — the demand and price "
      "tolerance your redesign may not exceed):"
    )
    lines.append(json.dumps(market_reality, ensure_ascii=False, default=str))
    lines.append("")
    lines.append(MARKET_SEMANTICS_PRIMER)
    lines.append("")
  lines.append("STATED FACTS (the operator's present-day reality — the starting line of the turnaround):")
  lines.append(json.dumps(stated_facts, ensure_ascii=False, default=str))
  lines.append("")
  lines.append(
    "CURRENT STRUCTURE (how the as-stated plan is shaped today — the "
    "structure that did not work):"
  )
  lines.append(json.dumps(current_structure, ensure_ascii=False, default=str))
  if prior_design:
    lines.append("")
    lines.append("YOUR PREVIOUS RESTRUCTURE DESIGN:")
    lines.append(json.dumps(prior_design, ensure_ascii=False, default=str))
  if solver_gap_report:
    lines.append("")
    lines.append(
      "SOLVER GAP REPORT (your calculator's feedback on that design — "
      "where it landed and where it fell short; redesign realistically, "
      "do not shave numbers):"
    )
    lines.append(json.dumps(solver_gap_report, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_design_restructure_once(
  *,
  compact: Dict[str, Any],
  stated_facts: Dict[str, Any],
  current_structure: Dict[str, Any],
  prior_design: Optional[Dict[str, Any]] = None,
  solver_gap_report: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """ONE restructure-design call (locked). Returns ``{ok, design, error}``
  (RAW — pass through ``validate_restructure_design``)."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "design": None, "error": "openai_api_key_unset"}
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
        prior_design=prior_design, solver_gap_report=solver_gap_report,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_restructure_design"}},
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
    return {"ok": False, "design": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}
  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "design": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "design": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}
  if not isinstance(parsed, dict) or "restructure_feasible" not in parsed:
    return {"ok": False, "design": None, "error": "no_design_in_tool_call"}
  return {"ok": True, "design": parsed, "error": None}


def validate_restructure_design(
  *,
  design: Dict[str, Any],
  stated_owner_annual_wage: float,
) -> Dict[str, Any]:
  """Rail the raw design into an executable directive.

  The rails here are ARITHMETIC COHERENCE only (the four reality
  constraints are the design fence; no viability ceilings exist in
  restructure mode): price multipliers bounded to a sane order of
  magnitude, growth to a believable annual range, team payroll never
  below the owner's own wage (the founder runs the business), all four
  constraint attestations present or the design is not valid.
  """
  notes: List[str] = []
  d = design or {}
  feasible = bool(d.get("restructure_feasible"))
  rc = d.get("reality_constraints") if isinstance(d.get("reality_constraints"), dict) else {}
  attestations = {
    k: str(rc.get(k) or "").strip()
    for k in ("real_market", "real_physics", "still_this_business", "lender_defensible")
  }
  if feasible and not all(attestations.values()):
    feasible = False
    notes.append("design_rejected_missing_reality_attestations")

  p_lo, p_hi = RESTRUCTURE_RAILS["price_multiplier"]
  g_lo, g_hi = RESTRUCTURE_RAILS["annual_growth"]

  def _clamp(value: Optional[float], lo: float, hi: float, name: str, fallback: float) -> float:
    v = _num(value)
    if v is None:
      notes.append(f"{name}_missing_default_{fallback}")
      return float(fallback)
    c = min(max(float(v), lo), hi)
    if abs(c - float(v)) > 1e-9:
      notes.append(f"{name}_clamped_{float(v):.4f}->{c:.4f}")
    return c

  team = d.get("team") if isinstance(d.get("team"), dict) else {}
  owner_wage = max(0.0, float(stated_owner_annual_wage or 0.0))
  team_payroll = _num(team.get("annual_payroll"))
  if team_payroll is None or team_payroll <= 0:
    feasible = False
    notes.append("design_rejected_no_team_payroll")
    team_payroll = 0.0
  elif owner_wage > 0 and team_payroll < owner_wage:
    notes.append(f"team_payroll_floored_at_owner_wage_{team_payroll:.0f}->{owner_wage:.0f}")
    team_payroll = owner_wage

  pricing = d.get("pricing") if isinstance(d.get("pricing"), dict) else {}
  facility = d.get("facility") if isinstance(d.get("facility"), dict) else {}
  growth = d.get("growth") if isinstance(d.get("growth"), dict) else {}
  rent_target = _num(facility.get("quarterly_rent_target"))

  # -- REVENUE MIX (the holistic revenue-side surface) --
  v_lo, v_hi = RESTRUCTURE_RAILS["volume_multiplier"]
  c_lo, c_hi = RESTRUCTURE_RAILS["cost_percent_of_revenue"]
  m_lo, m_hi = RESTRUCTURE_RAILS["new_line_gross_margin"]
  mix_raw = d.get("revenue_mix") if isinstance(d.get("revenue_mix"), dict) else {}
  mix_lines: List[Dict[str, Any]] = []
  for entry in (mix_raw.get("lines") or []):
    if not isinstance(entry, dict):
      continue
    lob = str(entry.get("lob") or "").strip()
    product = str(entry.get("product") or "").strip()
    if not (lob or product):
      notes.append("mix_line_skipped_no_identity")
      continue
    mix_lines.append({
      "lob": lob[:120],
      "product": product[:120],
      "volume_multiplier_q11": _clamp(entry.get("volume_multiplier_q11"), v_lo, v_hi, f"vol_q11_{product or lob}", 1.0),
      "volume_multiplier_q20": _clamp(entry.get("volume_multiplier_q20"), v_lo, v_hi, f"vol_q20_{product or lob}", 1.0),
      "price_multiplier_q11": _clamp(entry.get("price_multiplier_q11"), p_lo, p_hi, f"line_price_q11_{product or lob}", 1.0),
      "price_multiplier_q20": _clamp(entry.get("price_multiplier_q20"), p_lo, p_hi, f"line_price_q20_{product or lob}", 1.0),
      "rationale": str(entry.get("rationale") or "")[:400],
    })
  new_lines: List[Dict[str, Any]] = []
  for entry in (mix_raw.get("new_lines") or [])[: int(RESTRUCTURE_RAILS["max_new_lines"])]:
    if not isinstance(entry, dict):
      continue
    lob = str(entry.get("lob") or "").strip()
    product = str(entry.get("product") or "").strip()
    unit_price = _num(entry.get("unit_price"))
    rev_target = _num(entry.get("q11_quarterly_revenue_target"))
    if not (lob or product) or unit_price is None or unit_price <= 0 or rev_target is None or rev_target <= 0:
      notes.append("new_line_skipped_incomplete")
      continue
    new_lines.append({
      "lob": lob[:120] or "New",
      "product": product[:120] or "New Line",
      "unit_price": round(float(unit_price), 2),
      "q11_quarterly_revenue_target": round(float(rev_target), 2),
      "gross_margin_pct": _clamp(entry.get("gross_margin_pct"), m_lo, m_hi, f"newline_margin_{product or lob}", 0.50),
      "rationale": str(entry.get("rationale") or "")[:400],
    })
  cost_raw = d.get("cost_structure") if isinstance(d.get("cost_structure"), dict) else {}
  cost_structure: Dict[str, Any] = {"rationale": str(cost_raw.get("rationale") or "")[:500]}
  for key in ("cogs_percent_of_revenue", "marketing_percent_of_revenue", "g_and_a_percent_of_revenue"):
    val = _num(cost_raw.get(key))
    cost_structure[key] = (
      _clamp(val, c_lo, c_hi, f"cost_{key}", 0.0) if val is not None else None
    )

  return {
    "feasible": feasible,
    "team": {
      "annual_payroll": round(float(team_payroll), 2),
      "structure": str(team.get("structure") or "")[:300],
      "rationale": str(team.get("rationale") or "")[:500],
    },
    "pricing": {
      "price_multiplier_q11": _clamp(pricing.get("price_multiplier_q11"), p_lo, p_hi, "price_q11", 1.0),
      "price_multiplier_q20": _clamp(pricing.get("price_multiplier_q20"), p_lo, p_hi, "price_q20", 1.0),
      "rationale": str(pricing.get("rationale") or "")[:500],
    },
    "facility": {
      "quarterly_rent_target": (round(max(0.0, float(rent_target)), 2) if rent_target is not None else None),
      "rationale": str(facility.get("rationale") or "")[:500],
    },
    "growth": {
      "year1_annual_growth": _clamp(growth.get("year1_annual_growth"), g_lo, g_hi, "growth_y1", 0.05),
      "mature_annual_growth": _clamp(growth.get("mature_annual_growth"), g_lo, g_hi, "growth_mature", 0.03),
      "rationale": str(growth.get("rationale") or "")[:500],
    },
    "revenue_mix": {
      "lines": mix_lines,
      "new_lines": new_lines,
    },
    "cost_structure": cost_structure,
    "product_mix_notes": str(d.get("product_mix_notes") or "")[:500],
    "overall_rationale": str(d.get("overall_rationale") or "")[:900],
    "reality_constraints": attestations,
    "notes": notes,
  }


def build_solver_gap_report(
  *,
  acceptance_verdict: Dict[str, Any],
  finmo_json: Dict[str, Any],
) -> Dict[str, Any]:
  """The SOLVER's feedback to the executive between design rounds:
  the verdict, the failing checks, and where the plan actually landed
  (deterministic — pure arithmetic off the crunched plan)."""
  verdict = acceptance_verdict if isinstance(acceptance_verdict, dict) else {}
  rows = {
    int(_num(r.get("quarter_index")) or 0): r
    for r in ((finmo_json or {}).get("quarter_rows") or [])
    if isinstance(r, dict)
  }

  def _q(qi: int) -> Dict[str, Any]:
    r = rows.get(qi) or {}
    rev = float(_num(r.get("revenue")) or 0.0)
    if rev <= 0:
      return {"revenue": 0}
    return {
      "revenue": round(rev),
      "ebitda_margin": round(float(_num(r.get("ebitda")) or 0.0) / rev, 4),
      "net_income_margin": round(float(_num(r.get("net_income")) or 0.0) / rev, 4),
      "payroll_pct": round(float(_num(r.get("payroll")) or 0.0) / rev, 4),
      "rent_pct": round(float(_num(r.get("lease_rent")) or 0.0) / rev, 4),
      "cogs_pct": round(float(_num(r.get("cogs")) or 0.0) / rev, 4),
      "g_and_a_pct": round(float(_num(r.get("general_and_administrative")) or 0.0) / rev, 4),
    }

  return {
    "viable": bool(verdict.get("passed")),
    "failed_checks": list(verdict.get("failed_checks") or []),
    "landed": {"q1": _q(1), "q5": _q(5), "q11": _q(11), "q20": _q(20)},
    "note": (
      "The Q11 checkpoint requires EBITDA recovered to positive and the "
      "net-income ramp landing at/above zero; the mature margin is judged "
      "against the business's healthy band."
    ),
  }


def stated_owner_annual_wage(people_json: Optional[Dict[str, Any]]) -> float:
  total = 0.0
  for p in ((people_json or {}).get("people") or []):
    if not isinstance(p, dict):
      continue
    title = str(p.get("role_title") or p.get("role") or p.get("title") or "").lower()
    if any(tok in title for tok in OWNER_TITLE_TOKENS):
      total += float(_num(p.get("annual_wage")) or 0.0)
  return total


__all__ = [
  "gpt_design_restructure_once",
  "validate_restructure_design",
  "build_solver_gap_report",
  "stated_owner_annual_wage",
  "RESTRUCTURE_RAILS",
]
