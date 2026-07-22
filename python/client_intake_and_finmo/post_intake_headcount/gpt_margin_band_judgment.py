"""The executive-manager's HEALTHY-MARGIN BAND JUDGMENT.

The EBITDA/margin band is the pass/fail STANDARD the whole pipeline
judges against — and until now it was the one major judgment the
executive did not control. Cost, revenue, growth, payroll, working
capital, deferred revenue, capital structure: all executive-judged.
The band stayed mechanically derived (arithmetic over fitted cost
bands), so any business whose real economics don't match the mechanical
derivation failed with no executive to say "this band is wrong for this
business". Orion (band omitted R&D), Luna (fashion's high COGS), and
Riverbend (auto retail's structural 86% COGS and industry-wide 1-4%
net margins) were all the same disease: THE BAND DIDN'T UNDERSTAND THE
BUSINESS.

This module gives the executive the band: it judges the realistic,
HEALTHY EBITDA-margin range for THIS SPECIFIC BUSINESS from the full
business picture (identity, what it sells, price points, how it makes
money, scale, structural cost reality, business model, market) — NOT a
sector/NAICS lookup (cohort-defaults again) and NOT a purely mechanical
derivation. A high-volume used-car lot gets a thin low-single-digit
band; a software company gets a fat band; a boutique gets fashion-
retail economics. Each from its own full picture, each defensible to a
lender ("used-car retail runs 2-4%; this plan is in range").

THE FENCE — the band is the JUDGE, not a lever, so this is the
highest-stakes judgment the executive holds:
  1. VIABILITY-BLIND, HARD: the prompt NEVER sees where the plan's
     EBITDA actually lands, what any gate needs, or whether anything
     passes. The judgment reasons "what margin is healthy for this kind
     of business" from identity and structural facts only. If this
     judgment could see the plan's numbers, it would be wrong by
     construction.
  2. HONEST BAR, NOT A LOWERED ONE: the band is what a HEALTHY business
     of this type earns. A genuinely failing business still fails —
     the executive gives auto retail a thin-but-REAL band, and a doomed
     dealer can't meet even that. The rails additionally floor the
     mature band at the universal Q11 doctrine (recovered to >= 0 by
     Q11): the judgment can size the bar to the business, never waive
     viability itself.
  3. DETERMINISTIC: one locked call (run-once-and-lock) authored once
     per run; a failed call leaves the mechanically derived band
     exactly as it is today.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

# Python rails — believable ranges for a small-business EBITDA margin.
# The executive judges WITHIN these; a rogue judgment can neither waive
# the Q11-positive doctrine (low floored at 0) nor demand a fantasy
# margin (high capped at 55/60%).
MARGIN_BAND_RAILS: Dict[str, Any] = {
  "q11_low": (0.0, 0.35),
  "q11_high_max": 0.55,
  "q20_low_max": 0.40,
  "q20_high_max": 0.60,
  "min_width": 0.01,
  # Structural floors (replace the Phase-E placeholder constants when
  # judged): arithmetic-sanity clamps only, never viability levers.
  "gross_margin_floor": (0.05, 0.90),
  "fixed_cost_burden_max": (0.30, 0.90),
}


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_margin_band_judgment",
    "description": (
      "Submit the healthy EBITDA-margin band judgment for this business. "
      "Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "q11_ebitda_band": {
          "type": "object",
          "description": (
            "The EBITDA-margin range (fractions of revenue) a HEALTHY "
            "business of this type runs at the ~year-3 establishing "
            "checkpoint (Q11)."
          ),
          "properties": {
            "low": {
              "type": "number",
              "description": (
                "The bottom of the healthy range at Q11 — the level below "
                "which a lender would say this business is not yet working."
              ),
            },
            "high": {
              "type": "number",
              "description": (
                "The top of the realistic range at Q11 — above this the "
                "forecast stops being believable for this business type."
              ),
            },
          },
          "required": ["low", "high"],
        },
        "q20_ebitda_band": {
          "type": "object",
          "description": (
            "The EBITDA-margin range a healthy MATURE business of this "
            "type sustains (~year 5, Q20)."
          ),
          "properties": {
            "low": {"type": "number"},
            "high": {"type": "number"},
          },
          "required": ["low", "high"],
        },
        "gross_margin_floor_q11": {
          "type": "number",
          "description": (
            "STRUCTURAL FLOOR (fraction of revenue): the minimum Q11 "
            "GROSS margin (revenue minus direct/product costs) consistent "
            "with a real, recovering business of THIS character. A fuel "
            "distributor or grocer runs thin gross margins healthily; a "
            "consultancy below ~50% is structurally broken. Judge from "
            "what the product physically costs to deliver — not from any "
            "plan number."
          ),
        },
        "fixed_cost_burden_max_q11": {
          "type": "number",
          "description": (
            "STRUCTURAL CEILING (fraction of revenue): the maximum "
            "payroll + rent + G&A share of revenue a healthy business of "
            "this character carries at the Q11 establishing checkpoint. "
            "Expert-labor practices run high fixed shares healthily; "
            "capital-light distribution runs low. Judge from how this "
            "kind of business is actually staffed and housed."
          ),
        },
        "margin_character": {
          "type": "string",
          "description": (
            "One phrase naming the margin model (e.g. 'thin-margin "
            "high-volume retail', 'high-operating-leverage software', "
            "'labor-bound personal services')."
          ),
        },
        "rationale": {
          "type": "string",
          "description": (
            "The lender defense of this band on the business's structural "
            "merits: how it makes money, what its cost structure forces, "
            "what healthy peers of this SPECIFIC kind actually earn "
            "(3-4 sentences)."
          ),
        },
      },
      "required": [
        "q11_ebitda_band", "q20_ebitda_band",
        "gross_margin_floor_q11", "fixed_cost_burden_max_q11",
        "margin_character", "rationale",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER judging the HEALTHY EBITDA-MARGIN BAND "
  "for one specific business — the realistic range a genuinely healthy "
  "business of this exact kind earns at its ~year-3 establishing point "
  "(Q11) and at maturity (~year 5, Q20). This band becomes the standard "
  "the business plan is judged against, so it must be the honest bar for "
  "the business type: neither an aspiration the type cannot structurally "
  "reach, nor a lowered bar that lets a failing business look healthy.\n"
  "THE FENCE: you are told NOTHING about the plan's own margins, gaps, or "
  "verdicts — and you must never try to infer or accommodate them. You "
  "judge the BUSINESS TYPE at this business's specific scale and model, "
  "not any plan. Every number must be one you could defend to a "
  "small-business lender with a sentence like 'healthy used-car retail "
  "runs 2-4% EBITDA; healthy niche software runs 15-30%'.\n"
  "HOW TO JUDGE:\n"
  "1. REASON FROM WHAT THE BUSINESS IS — what it sells, at what price "
  "points, to whom, through what model, at what scale. NOT from a sector "
  "statistic: a NAICS average is a cohort default, and cohort defaults "
  "are exactly what this judgment replaces.\n"
  "2. STRUCTURAL COST REALITY SETS THE CEILING: a reseller of expensive "
  "physical goods (vehicles, jewelry wholesale-to-retail) runs high-80s "
  "COGS and earns thin single-digit margins on volume — that is HEALTHY "
  "for the type, and demanding 15% of it is judging the wrong business. "
  "A software/IP business with near-zero marginal cost healthily earns "
  "high-teens-to-30s at maturity, and granting it a thin band would bless "
  "underperformance. Labor-bound services sit between, bounded by wages.\n"
  "3. SCALE AND OWNER ECONOMICS MATTER: a solo studio or two-person "
  "practice carries owner economics and light overhead; a multi-million-"
  "dollar operation carries real fixed structure. An owner-operator who "
  "pays themselves through the payroll line has ALREADY taken the "
  "owner's living out of the P&L — the healthy residual EBITDA of such a "
  "business is structurally lower than the sector's headline statistic, "
  "and demanding the headline anyway double-counts the owner's pay. "
  "Judge THIS business's scale and structure.\n"
  "4. THE BAND IS A RANGE, NOT A POINT — AND THE LOW IS A MINIMUM-"
  "SOUNDNESS BAR, NOT TYPICAL HEALTH: low = the margin BELOW which a "
  "lender would refuse to renew this business's loan (fundamentally not "
  "working), not the middle of the healthy pack. Calibrate it with the "
  "arithmetic: start from 100%, subtract the stated structural lines "
  "(COGS, payroll, rent) and realistic remaining overhead, and ask what "
  "a competently-run business of this type has LEFT — if your low is "
  "above what that arithmetic permits for a sound operator, your low is "
  "wrong. A business the lender would happily renew must sit INSIDE "
  "your band. high = above this, the forecast stops being believable "
  "for the type. Q20 may sit at or above Q11 as the business matures — "
  "never below.\n"
  "5. HONESTY IN BOTH DIRECTIONS: the band must be reachable by a healthy "
  "operator of this type AND missable by a failing one. If you find "
  "yourself stretching the band, you are judging a plan, not a business — "
  "stop.\n"
  "6. EBITDA IS PRE-INTEREST — DO NOT ANCHOR ON POST-DEBT-SERVICE "
  "TALK: operators and industry chatter quote margins AFTER structural "
  "debt service (inventory/floorplan finance, equipment notes, "
  "mortgages on the operating asset). Your band judges EBITDA, which "
  "is BEFORE interest. A business whose MODEL structurally finances "
  "its assets with debt must hold pre-interest margins high enough to "
  "SERVICE that structural debt and still clear net health — its "
  "believable EBITDA band sits ABOVE its net-margin conversation by "
  "roughly the structural interest load. This is a framing rule, not "
  "an industry rule: apply it wherever the model itself implies "
  "debt-financed assets, and NOWHERE else — a business without "
  "structural debt has no wedge, and its band must NOT be inflated.\n"
  "7. TWO STRUCTURAL FLOORS ride the same judgment, same fence, same "
  "lender defense: gross_margin_floor_q11 — the minimum Q11 GROSS margin "
  "a real business of this character needs to be recovering (thin for "
  "distribution/grocery/fuel where pennies on the dollar are healthy; "
  "high for services and IP where product cost is small); and "
  "fixed_cost_burden_max_q11 — the maximum payroll+rent+G&A share of "
  "revenue a healthy business of this character carries at Q11 (high for "
  "expert-labor practices, low for capital-light volume models). Derive "
  "both from the same structural arithmetic as the band — they must be "
  "consistent with it (a gross-margin floor minus a burden ceiling that "
  "makes your own EBITDA band unreachable is self-contradictory).\n"
  "Call submit_margin_band_judgment exactly once."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  stated_cost_facts: Optional[Dict[str, Any]],
) -> str:
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
    MARKET_SEMANTICS_PRIMER,
  )
  _compact = dict(compact or {})
  market_reality = {
    k: _compact.pop(k) for k in ("target_market", "market_demand") if k in _compact
  }
  lines: List[str] = []
  lines.append("BUSINESS COMPACT (what this business IS — judge the band from this):")
  lines.append(json.dumps(_compact, ensure_ascii=False, default=str))
  lines.append("")
  if market_reality:
    lines.append(
      "MARKET REALITY (who buys, at what price points, how stable — the "
      "margin model must respect this):"
    )
    lines.append(json.dumps(market_reality, ensure_ascii=False, default=str))
    lines.append("")
    lines.append(MARKET_SEMANTICS_PRIMER)
    lines.append("")
  if stated_cost_facts:
    lines.append(
      "OPERATOR-STATED PRESENT-DAY COST STRUCTURE (fractions of revenue — "
      "structural FACTS about how this business's economics work today, "
      "e.g. the COGS a reseller of expensive goods carries; NOT a plan "
      "and NOT a target):"
    )
    lines.append(json.dumps(stated_cost_facts, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_margin_band_once(
  *,
  compact: Dict[str, Any],
  stated_cost_facts: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE margin-band judgment call; return ``{ok, judgment, error}``
  (RAW — callers must pass it through ``validate_margin_band_judgment``).

  ``ok=False`` -> the mechanically derived band stands (today's exact
  behavior)."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "judgment": None, "error": "openai_api_key_unset"}

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
        compact=compact, stated_cost_facts=stated_cost_facts,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_margin_band_judgment"}},
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
    return {"ok": False, "judgment": None, "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}

  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "judgment": None, "error": f"http_status_{status}:{str(getattr(resp, 'text', ''))[:300]}"}
  try:
    body = resp.json()
    choices = body.get("choices") or []
    message = choices[0].get("message") if choices else None
    tool_calls = (message or {}).get("tool_calls") or []
    fn = (tool_calls[0] or {}).get("function") if tool_calls else None
    args_raw = (fn or {}).get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else None)
  except Exception as exc:
    return {"ok": False, "judgment": None, "error": f"tool_call_parse_failed:{type(exc).__name__}"}

  if not isinstance(parsed, dict):
    return {"ok": False, "judgment": None, "error": "no_judgment_in_tool_call"}
  for key in ("q11_ebitda_band", "q20_ebitda_band"):
    if not isinstance(parsed.get(key), dict):
      return {"ok": False, "judgment": None, "error": f"band_missing:{key}"}
  return {"ok": True, "judgment": parsed, "error": None}


def validate_margin_band_judgment(
  *,
  judgment: Dict[str, Any],
) -> Dict[str, Any]:
  """Rail the raw judgment into a validated, executable band.

  - Q11 low clamped into [0.0, 0.35]: the universal Q11-positive doctrine
    is the floor the judgment cannot waive, and 35% is the believability
    cap for a small-business establishing margin.
  - Highs at least ``min_width`` above their lows; capped at 55%/60%.
  - Q20 (mature) low never below Q11 low (hold-or-improve doctrine).

  Returns {q11: {low, high, target}, q20: {low, high, target},
  margin_character, rationale, notes[...]}.
  """
  notes: List[str] = []
  j = judgment or {}

  def _num(value: Any, fallback: float) -> float:
    try:
      v = float(value)
      if v != v:
        return fallback
      return v
    except (TypeError, ValueError):
      return fallback

  q11 = j.get("q11_ebitda_band") or {}
  q20 = j.get("q20_ebitda_band") or {}
  lo_rail, lo_rail_hi = MARGIN_BAND_RAILS["q11_low"]
  min_width = float(MARGIN_BAND_RAILS["min_width"])

  q11_low_raw = _num(q11.get("low"), lo_rail)
  q11_low = max(float(lo_rail), min(float(lo_rail_hi), q11_low_raw))
  if abs(q11_low - q11_low_raw) > 1e-9:
    notes.append(f"q11_low_clamped_{q11_low_raw:.4f}->{q11_low:.4f}")
  q11_high_raw = _num(q11.get("high"), q11_low + min_width)
  q11_high = max(q11_low + min_width, min(float(MARGIN_BAND_RAILS["q11_high_max"]), q11_high_raw))
  if abs(q11_high - q11_high_raw) > 1e-9:
    notes.append(f"q11_high_clamped_{q11_high_raw:.4f}->{q11_high:.4f}")

  q20_low_raw = _num(q20.get("low"), q11_low)
  q20_low = max(q11_low, min(float(MARGIN_BAND_RAILS["q20_low_max"]), q20_low_raw))
  if abs(q20_low - q20_low_raw) > 1e-9:
    notes.append(f"q20_low_clamped_{q20_low_raw:.4f}->{q20_low:.4f}")
  q20_high_raw = _num(q20.get("high"), q20_low + min_width)
  q20_high = max(q20_low + min_width, min(float(MARGIN_BAND_RAILS["q20_high_max"]), q20_high_raw))
  if abs(q20_high - q20_high_raw) > 1e-9:
    notes.append(f"q20_high_clamped_{q20_high_raw:.4f}->{q20_high:.4f}")

  # STRUCTURAL FLOORS (additive — replace the Phase-E placeholder
  # constants only when judged and self-consistent; absent fields leave
  # every consumer on its current fallback constant).
  gm_floor: Optional[float] = None
  burden_max: Optional[float] = None
  gm_raw = j.get("gross_margin_floor_q11")
  if gm_raw is not None:
    gm_lo, gm_hi = MARGIN_BAND_RAILS["gross_margin_floor"]
    gm_val = _num(gm_raw, -1.0)
    if gm_val >= 0.0:
      gm_floor = max(float(gm_lo), min(float(gm_hi), gm_val))
      if abs(gm_floor - gm_val) > 1e-9:
        notes.append(f"gm_floor_clamped_{gm_val:.4f}->{gm_floor:.4f}")
  bm_raw = j.get("fixed_cost_burden_max_q11")
  if bm_raw is not None:
    bm_lo, bm_hi = MARGIN_BAND_RAILS["fixed_cost_burden_max"]
    bm_val = _num(bm_raw, -1.0)
    if bm_val >= 0.0:
      burden_max = max(float(bm_lo), min(float(bm_hi), bm_val))
      if abs(burden_max - bm_val) > 1e-9:
        notes.append(f"burden_max_clamped_{bm_val:.4f}->{burden_max:.4f}")
  # Self-consistency vs the judgment's OWN EBITDA band — the one
  # airtight arithmetic relation: EBITDA can never exceed gross margin,
  # so a gross-margin FLOOR below the judged Q11 EBITDA band LOW is
  # self-contradictory (a business at that floor could not reach the
  # band's own minimum). Drop the floor (fallback constant governs)
  # rather than ship a self-inconsistent judgment. No corner test on
  # the burden ceiling — high-burden + high-GM expert-labor models are
  # a legitimate corner a joint test would wrongly punish.
  if gm_floor is not None and gm_floor < q11_low - 1e-9:
    notes.append(
      f"gm_floor_dropped_below_own_ebitda_band_low_{gm_floor:.4f}<{q11_low:.4f}"
    )
    gm_floor = None

  return {
    "q11": {
      "low": round(q11_low, 4),
      "high": round(q11_high, 4),
      "target": round((q11_low + q11_high) / 2.0, 4),
    },
    "q20": {
      "low": round(q20_low, 4),
      "high": round(q20_high, 4),
      "target": round((q20_low + q20_high) / 2.0, 4),
    },
    "gross_margin_floor_q11": (round(gm_floor, 4) if gm_floor is not None else None),
    "fixed_cost_burden_max_q11": (round(burden_max, 4) if burden_max is not None else None),
    "margin_character": str(j.get("margin_character") or "")[:120],
    "rationale": str(j.get("rationale") or "")[:600],
    "notes": notes,
  }


def margin_band_from_model_input(
  model_input_json: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """Read the validated judgment stamped at authoring time. Returns None
  when absent (every consumer then keeps the mechanically derived band)."""
  if not isinstance(model_input_json, dict):
    return None
  solver_input = model_input_json.get("solver_input")
  if not isinstance(solver_input, dict):
    return None
  judgment = solver_input.get("margin_band_judgment")
  if not isinstance(judgment, dict):
    return None
  q11 = judgment.get("q11")
  q20 = judgment.get("q20")
  if not isinstance(q11, dict) or not isinstance(q20, dict):
    return None
  return judgment


def judged_ebitda_floor_for_quarter(
  judgment: Optional[Dict[str, Any]], quarter_index: Optional[int],
) -> Optional[float]:
  """The judged healthy-band FLOOR for a mature quarter (Q11+): linear
  glide from the Q11 band low to the Q20 band low. Quarters before Q11
  return None — the ramp keeps the planning-mode recovery glidepath; the
  judged band judges the ESTABLISHED business, not the climb."""
  if not isinstance(judgment, dict) or quarter_index is None:
    return None
  q = int(quarter_index)
  if q < 11:
    return None
  try:
    q11_low = float((judgment.get("q11") or {}).get("low"))
    q20_low = float((judgment.get("q20") or {}).get("low"))
  except (TypeError, ValueError):
    return None
  if q >= 20:
    return q20_low
  fraction = (q - 11) / 9.0  # 0.0 at Q11 -> 1.0 at Q20
  return q11_low + (q20_low - q11_low) * fraction


__all__ = [
  "gpt_author_margin_band_once",
  "validate_margin_band_judgment",
  "margin_band_from_model_input",
  "judged_ebitda_floor_for_quarter",
  "MARGIN_BAND_RAILS",
]
