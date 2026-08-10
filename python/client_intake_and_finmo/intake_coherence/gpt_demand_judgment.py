"""THE DEMAND JUDGE (Nick-ruled, all five rulings approved 2026-08-10).

Demand is the common dependency under three levers - price (raise it,
customers may leave), marketing (cut it, demand drops), volume (do
more, only if demand supports it). The judge turns the evidence the
app ALREADY HOLDS (the revived census/CBP-grounded demand model, the
client's own chosen segments, the price point, the business type) into
a business-SPECIFIC, BANDED, DIRECTIONAL demand-response judgment -
the margin-band pattern: GPT judges from data, the judgment becomes a
first-class value.

THE FENCE:
  1. The client is NEVER asked about demand or elasticity. The judge
     reasons from data; a client's VOLUNTEERED answer (the CW-022 #4
     clarifier) always overrides the judge - the judge fills silence.
  2. NO numeric elasticity, ever. Verdicts are directional with BANDS,
     and the walk consumes the CONSERVATIVE edge.
  3. VIABILITY-BLIND: the judge sees the business and its market,
     never the plan's gaps or verdicts.
  4. THIN-EVIDENCE DOCTRINE (non-negotiable, enforced in the
     VALIDATOR not the prompt): evidence_level is computed in PYTHON
     from what the demand model actually holds; when THIN, every
     verdict is WITHHELD - a thin judgment that says it is thin is
     honest; a confident fabricated number is the CW-022 disease.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

_PRICE_VERDICTS = ("holds_most", "meaningful_loss", "unsupported")
_MARKETING_VERDICTS = ("insensitive", "coupled", "dependent")

# Anti-false-precision floor: no band may claim to know demand response
# tighter than 10 percentage points.
_MIN_BAND_WIDTH = 0.10


def demand_evidence_level(
  marketing_model_json: Optional[Dict[str, Any]],
  market_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """PYTHON-side evidence classification (never GPT-claimed). RICH only
  when the demand model is genuinely grounded: ready, GPT-estimated
  (not a fallback), no missing dependencies, and the client actually
  chose market segments (or a B2B basis exists)."""
  mm = marketing_model_json if isinstance(marketing_model_json, dict) else {}
  mk = market_json if isinstance(market_json, dict) else {}
  reasons = []
  if not mm.get("ready"):
    reasons.append("demand_model_not_ready")
  if mm.get("missing_dependencies"):
    reasons.append("missing:" + ",".join(str(x) for x in mm["missing_dependencies"]))
  method = str(mm.get("estimation_method") or "")
  if method and not method.startswith("gpt_estimate"):
    reasons.append(f"fallback_estimate:{method}")
  has_b2c_basis = bool(mm.get("b2c_basis_counts"))
  has_b2b_basis = bool((mm.get("b2b_basis_counts") or {}).get("cbp_basis"))
  has_selections = bool(mk.get("selections"))
  if not (has_b2c_basis or has_b2b_basis or has_selections):
    reasons.append("no_market_basis_or_selections")
  return {"level": "thin" if reasons else "rich", "reasons": reasons}


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_demand_response_judgment",
    "description": "Submit the demand-response judgment. Call exactly once.",
    "parameters": {
      "type": "object",
      "properties": {
        "price_response": {
          "type": "object",
          "description": (
            "If this business raised prices toward the top of its "
            "believable market range, what happens to its existing "
            "demand? Judge the TYPE at its price point and market - "
            "never invent a precise percentage."
          ),
          "properties": {
            "verdict": {"type": "string", "enum": list(_PRICE_VERDICTS)},
            "retained_fraction_band": {
              "type": "array", "items": {"type": "number"},
              "minItems": 2, "maxItems": 2,
              "description": (
                "The believable RANGE of unit demand retained after a "
                "move to the judged price ceiling (fractions, e.g. "
                "[0.80, 0.95]). At least 10 points wide - narrower "
                "claims false precision."
              ),
            },
            "basis": {"type": "string"},
          },
          "required": ["verdict", "retained_fraction_band", "basis"],
        },
        "marketing_response": {
          "type": "object",
          "description": (
            "If this business cut marketing spend toward the judged "
            "floor, what happens to demand? 'insensitive': demand is "
            "mostly referral/repeat/location-driven; 'coupled': a real "
            "but partial demand cost; 'dependent': acquisition runs on "
            "spend and a cut cuts demand materially."
          ),
          "properties": {
            "verdict": {"type": "string", "enum": list(_MARKETING_VERDICTS)},
            "demand_at_reduced_spend_band": {
              "type": "array", "items": {"type": "number"},
              "minItems": 2, "maxItems": 2,
              "description": (
                "The believable RANGE of demand retained at floor-level "
                "marketing spend (fractions). At least 10 points wide."
              ),
            },
            "basis": {"type": "string"},
          },
          "required": ["verdict", "demand_at_reduced_spend_band", "basis"],
        },
        "volume_headroom": {
          "type": "object",
          "description": (
            "The most annual units this business's reachable market "
            "believably supports in year 1 - from the demand model's "
            "reach and capture arithmetic, not from capacity."
          ),
          "properties": {
            "supported_units_max": {"type": "number"},
            "basis": {"type": "string"},
          },
          "required": ["supported_units_max", "basis"],
        },
        "rationale": {"type": "string"},
      },
      "required": ["price_response", "marketing_response",
                   "volume_headroom", "rationale"],
    },
  },
}

_SYSTEM_PROMPT = (
  "You are the DEMAND JUDGE for one specific business. From the market "
  "evidence provided - the census/CBP-grounded demand model (reachable "
  "market, capture arithmetic, marketing intensity), the client's own "
  "chosen market segments, the price point against the judged believable "
  "price range, the business type and how it books work - judge how this "
  "business's DEMAND responds to the three moves a plan can make: raising "
  "price, cutting marketing, and selling more volume.\n"
  "RULES:\n"
  "1. JUDGE THE BUSINESS, not a formula. A repeat-service business with "
  "route density and switching friction holds customers differently than "
  "a discretionary one-off purchase. Reason from what the business IS.\n"
  "2. BANDS, NEVER POINTS: every quantity is a RANGE at least 10 points "
  "wide. A precise demand number would be fabricated - the range plus "
  "the reasoning IS the judgment.\n"
  "3. You are VIABILITY-BLIND: you know nothing about what any plan "
  "needs, and you must not try to help or hurt one. Judge demand as it "
  "is.\n"
  "4. Your basis strings must cite the EVIDENCE (reach, segments, price "
  "position, repeat behavior), not restate the verdict.\n"
  "Call submit_demand_response_judgment exactly once."
)


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


def gpt_author_demand_response_once(
  *,
  compact: Dict[str, Any],
  marketing_model: Dict[str, Any],
  price_facts: Dict[str, Any],
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """ONE demand-response call; returns {ok, judgment, error}. RAW -
  callers must pass the result through validate_demand_response."""
  api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
  if api_key is None:
    return {"ok": False, "judgment": None, "error": "openai_api_key_unset"}
  http_fn = _http
  if http_fn is None:
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries,
    )
    http_fn = post_openai_with_retries
  user = (
    "BUSINESS COMPACT (what this business IS):\n"
    + json.dumps(compact or {}, ensure_ascii=False, default=str)
    + "\n\nDEMAND MODEL (census/CBP-grounded, planning-level):\n"
    + json.dumps({k: (marketing_model or {}).get(k) for k in (
        "reachable_market", "reachable_market_b2c", "reachable_market_b2b",
        "capture_rate_year1", "expected_customers_or_clients_year1",
        "expected_units_year1", "required_units_year1",
        "marketing_intensity", "baseline_marketing_percent",
        "marketing_basis_summary", "market_basis_type",
      )}, ensure_ascii=False, default=str)
    + "\n\nPRICE POSITION:\n"
    + json.dumps(price_facts or {}, ensure_ascii=False, default=str)
  )
  payload = {
    "model": _resolve_model(model),
    "messages": [
      {"role": "system", "content": _SYSTEM_PROMPT},
      {"role": "user", "content": user},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function",
                    "function": {"name": "submit_demand_response_judgment"}},
    "seed": int(seed),
  }
  headers = {"Authorization": f"Bearer {api_key}",
             "Content-Type": "application/json"}
  try:
    resp = http_fn(
      url=_OPENAI_URL, headers=headers, payload=payload,
      timeout_seconds=timeout_seconds,
      retryable_status=(429, 500, 502, 503, 504), max_attempts=3,
    )
  except Exception as exc:
    return {"ok": False, "judgment": None,
            "error": f"http_error:{type(exc).__name__}:{str(exc)[:200]}"}
  status = int(getattr(resp, "status_code", 0) or 0)
  if status != 200:
    return {"ok": False, "judgment": None, "error": f"http_status_{status}"}
  try:
    body = resp.json()
    message = (body.get("choices") or [{}])[0].get("message") or {}
    fn = ((message.get("tool_calls") or [{}])[0] or {}).get("function") or {}
    args_raw = fn.get("arguments")
    parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
  except Exception as exc:
    return {"ok": False, "judgment": None,
            "error": f"tool_call_parse_failed:{type(exc).__name__}"}
  if not isinstance(parsed, dict):
    return {"ok": False, "judgment": None, "error": "no_judgment_in_tool_call"}
  return {"ok": True, "judgment": parsed, "error": None}


def _rail_band(raw: Any) -> Optional[list]:
  """Clamp to [0,1], order, and enforce the minimum width by widening
  DOWNWARD around the upper value (the conservative direction: a
  too-narrow band gets a LOWER conservative edge, never a rosier one)."""
  if not isinstance(raw, (list, tuple)) or len(raw) != 2:
    return None
  try:
    lo, hi = float(raw[0]), float(raw[1])
  except (TypeError, ValueError):
    return None
  lo, hi = max(0.0, min(1.0, min(lo, hi))), max(0.0, min(1.0, max(lo, hi)))
  if hi - lo < _MIN_BAND_WIDTH:
    lo = max(0.0, hi - _MIN_BAND_WIDTH)
  return [round(lo, 4), round(hi, 4)]


def validate_demand_response(
  *,
  judgment: Dict[str, Any],
  evidence: Dict[str, Any],
) -> Dict[str, Any]:
  """Rail the raw judgment. THE THIN-EVIDENCE RULE IS ENFORCED HERE:
  thin evidence -> every verdict WITHHELD (None), whatever GPT said -
  the airtight guarantee that a thin draft can never carry a
  confident-looking demand number. Rich evidence -> bands clamped,
  ordered, floored at the 10-point anti-false-precision width."""
  j = judgment or {}
  level = str((evidence or {}).get("level") or "thin")
  notes = []
  out: Dict[str, Any] = {
    "evidence_level": level,
    "evidence_reasons": list((evidence or {}).get("reasons") or []),
    "rationale": str(j.get("rationale") or "")[:800],
  }
  if level != "rich":
    out.update({
      "price_response": None,
      "marketing_response": None,
      "volume_headroom": None,
      "withheld": True,
    })
    notes.append("verdicts_withheld_thin_evidence")
    out["notes"] = notes
    return out

  pr = j.get("price_response") or {}
  band = _rail_band(pr.get("retained_fraction_band"))
  verdict = str(pr.get("verdict") or "").strip().lower()
  out["price_response"] = (
    {"verdict": verdict, "retained_fraction_band": band,
     "basis": str(pr.get("basis") or "")[:500]}
    if verdict in _PRICE_VERDICTS and band else None
  )
  if out["price_response"] is None:
    notes.append("price_response_invalid_dropped")

  mr = j.get("marketing_response") or {}
  band_m = _rail_band(mr.get("demand_at_reduced_spend_band"))
  verdict_m = str(mr.get("verdict") or "").strip().lower()
  out["marketing_response"] = (
    {"verdict": verdict_m, "demand_at_reduced_spend_band": band_m,
     "basis": str(mr.get("basis") or "")[:500]}
    if verdict_m in _MARKETING_VERDICTS and band_m else None
  )
  if out["marketing_response"] is None:
    notes.append("marketing_response_invalid_dropped")

  vh = j.get("volume_headroom") or {}
  try:
    sup = float(vh.get("supported_units_max"))
    sup = sup if sup >= 0 else None
  except (TypeError, ValueError):
    sup = None
  out["volume_headroom"] = (
    {"supported_units_max": round(sup, 2),
     "basis": str(vh.get("basis") or "")[:500]}
    if sup is not None else None
  )
  if out["volume_headroom"] is None:
    notes.append("volume_headroom_invalid_dropped")

  out["withheld"] = False
  out["notes"] = notes
  return out
