"""Executive per-business LEVER CEILINGS (Phase B).

Phase B re-admits the revenue-side levers (Unit Price / Capacity /
Utilization) and the payroll lever to the viability search. Opening a
lever without a real-world limit is how a search fakes viability: jack
the price 3x, run utilization at 100%, cut the clinical staff — the
plan passes the gates and no lender believes a word of it.

The limit is an IDENTITY judgment, not a cohort statistic: a walk-in
boutique cannot triple its prices (competitors take the market); a
dental practice cannot run without its clinical staff. So the
identity-aware executive (GPT) sets the ceiling per business — "how far
can THIS business move this lever before a lender stops believing the
plan" — and Python ENFORCES it:

  - Every ceiling is clamped inside the conservative fallback rails the
    solver already carried (price <= 1.20x, capacity <= 1.50x,
    utilization <= 0.84, payroll floor >= half the authored target).
    The executive can only TIGHTEN reality, never widen it.
  - The search then treats ceiling x authored trajectory as the
    per-quarter upper bound (Q1 stays anchored — today's price is a
    fact, not a lever).

Determinism: one call per engaged business through
post_openai_with_retries, so the judgment rides the GPT response lock
(run-once-and-lock). A failed call returns ok=False and the caller
keeps the levers CLOSED (the pre-Phase-B conservative state) — a
failure can never widen the search.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

# Conservative outer rails (documented margins, matching the solver's
# long-standing revenue_unit fallbacks). The executive tightens WITHIN
# these; a rogue or over-optimistic judgment cannot exceed them.
PRICE_MULTIPLIER_RAIL = 1.20
CAPACITY_MULTIPLIER_RAIL = 1.50
UTILIZATION_RAIL = 0.84
# The payroll floor may not authorize cutting more than half the
# authored payroll target — an outer sanity rail, not the judgment.
PAYROLL_FLOOR_FRACTION_RAIL = 0.50


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_lever_ceilings",
    "description": (
      "Submit the lender-believability ceilings for this business's plan "
      "levers. Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "unit_price_max_multiplier": {
          "type": "number",
          "description": (
            "Maximum multiple of the AUTHORED price trajectory this business "
            "could really charge by the corresponding quarter (1.0 = no room "
            "to raise prices; 1.10 = up to +10% above the authored path). "
            "Judge from competition, price sensitivity, and what the "
            "business sells."
          ),
        },
        "unit_price_rationale": {"type": "string"},
        "capacity_max_multiplier": {
          "type": "number",
          "description": (
            "Maximum multiple of the AUTHORED capacity trajectory the "
            "business could really serve (space, equipment, staffing, "
            "logistics). 1.0 = the authored ramp is already the ceiling."
          ),
        },
        "capacity_rationale": {"type": "string"},
        "utilization_max": {
          "type": "number",
          "description": (
            "Maximum sustainable utilization RATE (fraction of capacity, "
            "0-1) this operation can really run at, given no-shows, "
            "seasonality, setup time. Most businesses cannot sustain above "
            "~0.85."
          ),
        },
        "utilization_rationale": {"type": "string"},
        "payroll_min_percent_of_revenue": {
          "type": ["number", "null"],
          "description": (
            "Only for a labor-bound business (given its payroll target): the "
            "MINIMUM payroll as a fraction of revenue the business can run "
            "at without understaffing what it genuinely needs to operate "
            "(clinical staff, service coverage). This is a FLOOR the search "
            "may never go below. null when payroll should not move at all."
          ),
        },
        "payroll_rationale": {"type": "string"},
      },
      "required": [
        "unit_price_max_multiplier",
        "capacity_max_multiplier",
        "utilization_max",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the executive setting the REAL-WORLD CEILINGS on a business plan's "
  "levers before a viability search runs. The search will move unit price, "
  "capacity, utilization (and, for a labor-bound business, payroll as a "
  "fraction of revenue) to try to reach profitability -- your ceilings are "
  "the only thing standing between an honest plan and a fantasy one.\n"
  "THE TEST for every ceiling: would a small-business LENDER reading this "
  "plan still believe it at that level? A walk-in boutique cannot triple "
  "prices -- competitors take the market. A room has a real throughput cap. "
  "No operation sustains 100% utilization. A dental practice cannot cut "
  "clinical staff below what patient volume requires.\n"
  "Judge from the BUSINESS IDENTITY (what it sells, to whom, at what point "
  "of sale) and its CURRENT AUTHORED PLAN (the anchors you are given). Be "
  "specific to THIS business, not the industry average. Tight ceilings are "
  "fine -- 1.0 means 'this lever must not move'. Never widen a ceiling to "
  "help the plan pass; the ceiling is what is TRUE, not what is needed.\n"
  "PRICING POWER COMES FROM THE BUSINESS MODEL, not from one retail "
  "instinct applied everywhere: commodity and walk-in goods live near "
  "competitor prices (tight ceiling), while differentiated IP -- software, "
  "specialized services, products with switching costs or contractual "
  "lock-in -- holds real headroom through tiering, value-based packaging, "
  "and renewal repricing. Judge how much pricing power THIS model actually "
  "has in THIS market; a tight retail-style price ceiling on a "
  "differentiated-IP business understates the honest lever exactly the "
  "way a loose one on a corner shop overstates it. The same for capacity: "
  "a room has a physical throughput cap; digital capacity is bounded by "
  "sales, onboarding, and support coverage instead -- name the REAL "
  "binding constraint for this model and set the ceiling from it.\n"
  "Call submit_lever_ceilings exactly once."
)


def _build_user_prompt(
  *,
  business_identity: Dict[str, Any],
  lever_anchors: Dict[str, Any],
  market_context: Optional[Dict[str, Any]] = None,
) -> str:
  lines: List[str] = []
  lines.append("BUSINESS IDENTITY (judge from this):")
  lines.append(json.dumps(business_identity, ensure_ascii=False, default=str))
  lines.append("")
  if market_context:
    # The ceilings this call sets — how far price / throughput / staffing can
    # move before a lender stops believing — are MARKET questions. Blind to
    # the audience's income band and the reachable market, the judgment was
    # inferring pricing power from a four-field identity.
    lines.append(
      "MARKET REALITY (the ceilings are bounded by this — who the customers "
      "are, their income band, how many are reachable, what the plan already "
      "assumes captured):"
    )
    lines.append(json.dumps(market_context, ensure_ascii=False, default=str))
    lines.append("")
    try:
      from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
        MARKET_SEMANTICS_PRIMER,
      )
      lines.append(MARKET_SEMANTICS_PRIMER)
      lines.append("")
    except Exception:
      pass
  lines.append(
    "CURRENT AUTHORED PLAN ANCHORS (the trajectories the search would move; "
    "multipliers you set apply ON TOP of these):"
  )
  lines.append(json.dumps(lever_anchors, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_lever_ceilings_once(
  *,
  business_identity: Dict[str, Any],
  lever_anchors: Dict[str, Any],
  market_context: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE ceilings call; return ``{ok, ceilings, error}`` where
  ``ceilings`` = {unit_price_max_multiplier, capacity_max_multiplier,
  utilization_max, payroll_min_percent_of_revenue, rationales:{...}} with
  every value already CLAMPED inside the conservative rails.

  ``ok=False`` -> the caller keeps the levers closed."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "ceilings": None, "error": "openai_api_key_unset"}

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
        business_identity=business_identity, lever_anchors=lever_anchors,
        market_context=market_context,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_lever_ceilings"}},
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
    return {"ok": False, "ceilings": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "ceilings": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "ceilings": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(parsed, dict):
    return {"ok": False, "ceilings": None, "error": "no_ceilings_in_tool_call"}

  def _num(key: str) -> Optional[float]:
    v = parsed.get(key)
    try:
      return float(v) if v is not None else None
    except (TypeError, ValueError):
      return None

  price_mult = _num("unit_price_max_multiplier")
  cap_mult = _num("capacity_max_multiplier")
  util_max = _num("utilization_max")
  if price_mult is None or cap_mult is None or util_max is None:
    return {"ok": False, "ceilings": None, "error": "missing_required_ceilings"}

  # ENFORCE the rails: the executive tightens within them, never widens.
  price_mult = min(max(price_mult, 1.0), PRICE_MULTIPLIER_RAIL)
  cap_mult = min(max(cap_mult, 1.0), CAPACITY_MULTIPLIER_RAIL)
  util_max = min(max(util_max, 0.0), UTILIZATION_RAIL)

  payroll_floor = _num("payroll_min_percent_of_revenue")
  authored_payroll_pct = None
  try:
    authored_payroll_pct = float(
      (lever_anchors or {}).get("payroll", {}).get("target_percent_of_revenue")
    )
  except (TypeError, ValueError, AttributeError):
    authored_payroll_pct = None
  if payroll_floor is not None and authored_payroll_pct and authored_payroll_pct > 0:
    payroll_floor = min(
      max(payroll_floor, authored_payroll_pct * PAYROLL_FLOOR_FRACTION_RAIL),
      authored_payroll_pct,
    )
  else:
    payroll_floor = None

  return {
    "ok": True,
    "ceilings": {
      "unit_price_max_multiplier": price_mult,
      "capacity_max_multiplier": cap_mult,
      "utilization_max": util_max,
      "payroll_min_percent_of_revenue": payroll_floor,
      "rationales": {
        "unit_price": str(parsed.get("unit_price_rationale") or "")[:300],
        "capacity": str(parsed.get("capacity_rationale") or "")[:300],
        "utilization": str(parsed.get("utilization_rationale") or "")[:300],
        "payroll": str(parsed.get("payroll_rationale") or "")[:300],
      },
    },
    "error": None,
  }


__all__ = [
  "gpt_author_lever_ceilings_once",
  "PRICE_MULTIPLIER_RAIL",
  "CAPACITY_MULTIPLIER_RAIL",
  "UTILIZATION_RAIL",
  "PAYROLL_FLOOR_FRACTION_RAIL",
]
