"""The executive-manager's WORKING-CAPITAL JUDGMENT (DSO / DIO / DPO).

Working capital was the last generic corner: AR / Inventory / AP Days
came from flat NAICS cohort targets held constant across all 20
quarters — the same number for a walk-in donut shop and a wholesale
supplier in the same sector. But the cash-conversion cycle is deeply
business-specific: a law firm bills and waits (high DSO, zero
inventory); a boutique collects at the register but sits on stock
(low DSO, heavy DIO); a cash donut shop has almost no working-capital
drag at all. Same split as the cost structure: the MANAGER judges how
THIS business collects, stocks, and pays; the MACHINE executes the
trajectory deterministically.

THE FENCE — identical to the cost author, and load-bearing here
because WC is a powerful fake-viable lever (collect faster / pay
slower = free cash that can paper over a real cash problem):
  1. VIABILITY-BLIND: the prompt never sees whether any plan passes.
     The judgment is what this business's collection / stocking /
     payment behavior REALLY is, never what a cash flow needs.
  2. Q1 = STATED FACTS: when the operator stated AR / inventory / AP
     balances, the implied Q1 days are computed from them and OVERRIDE
     the judged Q1 anchor — the manager judges the maturation
     trajectory, not a fictional starting point.
  3. LENDER-DEFENSIBLE BOUNDS: Python rails clamp every anchor
     (DSO <= 90, DIO <= 180, DPO <= 90 — the mapping table's own live
     bounds); inventory applicability stays NAICS-gated (an executive
     cannot invent inventory for a law firm).
  4. DETERMINISTIC: one locked call (run-once-and-lock); a failed call
     falls back to the flat NAICS seed (today's exact behavior).

BOUNDARY NOTE — the cash pass is NOT touched: the judged days flow
into the balance-sheet driver rows, the engine derives AR / Inventory /
AP balances from them exactly as before, and the existing cash pass
consumes the resulting cash flow unchanged.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

_WC_DRIVER_KEYS = (
  "ar_days", "inventory_days", "ap_days", "prepaid_pct", "deferred_pct",
)

# Python rails — mirror of the mapping table's live bounds (days rows:
# minimum_live_value=1.0, maximum 90/180/90; percent rows: [0.01, 0.20]
# prepaid / [0.01, 0.75] deferred). The executive judges WITHIN these;
# a rogue judgment cannot stretch DPO to 180, promise negative collection
# days, or defer more revenue than the mapping table itself allows.
WC_RAILS: Dict[str, Any] = {
  "ar_days": (1.0, 90.0),
  "inventory_days": (1.0, 180.0),
  "ap_days": (1.0, 90.0),
  "prepaid_pct": (0.01, 0.20),
  "deferred_pct": (0.01, 0.75),
}

_LEVER_ID_FOR_DRIVER: Dict[str, str] = {
  "ar_days": "balance_sheet::Accounts Receivable Days",
  "inventory_days": "balance_sheet::Inventory Days",
  "ap_days": "balance_sheet::Accounts Payable Days",
  "prepaid_pct": "balance_sheet::Prepaid Expenses (% of Revenue)",
  "deferred_pct": "balance_sheet::Deferred Revenue (% of Revenue)",
}

# Anchor field names in the submit tool, per driver unit.
_ANCHOR_FIELDS: Dict[str, Any] = {
  "days": (("q1_days", "q1"), ("q11_days", "q11"), ("q20_days", "q20")),
  "pct": (("q1_pct", "q1"), ("q11_pct", "q11"), ("q20_pct", "q20")),
}
_DRIVER_UNIT: Dict[str, str] = {
  "ar_days": "days", "inventory_days": "days", "ap_days": "days",
  "prepaid_pct": "pct", "deferred_pct": "pct",
}


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


def _driver_schema(label: str, unit: str = "days", extra: str = "") -> Dict[str, Any]:
  fields = _ANCHOR_FIELDS[unit]
  unit_note = (
    "days" if unit == "days"
    else "a FRACTION of quarterly revenue (0.03 = 3%)"
  )
  props: Dict[str, Any] = {
    "applicable": {
      "type": "boolean",
      "description": f"Whether {label} applies to this business at all.{extra}",
    },
  }
  for field_name, when in ((fields[0][0], "today (Q1)"), (fields[1][0], "by year 3 (Q11)"), (fields[2][0], "at maturity (Q20)")):
    props[field_name] = {
      "type": "number",
      "description": f"{label} {when}, in {unit_note}.",
    }
  props["rationale"] = {
    "type": "string",
    "description": (
      "The lender-facing defense of this driver for THIS business: how it "
      "actually collects / stocks / pays / prepays, and why the trajectory "
      "moves (or stays flat). 1-3 sentences."
    ),
  }
  return {
    "type": "object",
    "properties": props,
    "required": ["applicable"] + [f for f, _ in fields] + ["rationale"],
  }


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_wc_judgment",
    "description": (
      "Submit the working-capital judgment (DSO / DIO / DPO / prepaid / "
      "deferred-revenue trajectories) for this business. Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "ar_days": _driver_schema("Accounts Receivable Days (DSO)"),
        "inventory_days": _driver_schema(
          "Inventory Days (DIO)",
          extra=" Pure service businesses hold no inventory (applicable=false).",
        ),
        "ap_days": _driver_schema("Accounts Payable Days (DPO, blended)"),
        "prepaid_pct": _driver_schema(
          "Prepaid Expenses (% of quarterly revenue)", unit="pct",
        ),
        "deferred_pct": _driver_schema(
          "Deferred Revenue (% of quarterly revenue)", unit="pct",
          extra=(
            " ONLY businesses that genuinely collect cash BEFORE earning it "
            "(memberships, retainers, subscriptions, annual contracts billed "
            "upfront). Point-of-sale / bill-after-delivery businesses: "
            "applicable=false."
          ),
        ),
      },
      "required": [
        "ar_days", "inventory_days", "ap_days", "prepaid_pct", "deferred_pct",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER of this business, judging its CASH-"
  "CONVERSION CYCLE — how THIS business actually collects (DSO), stocks "
  "(DIO), and pays (DPO) — the way a competent operator would defend "
  "working-capital assumptions to a small-business LENDER.\n"
  "THE MODEL'S EXACT ROW DEFINITIONS (judge these, not textbook ratios):\n"
  "1. ACCOUNTS RECEIVABLE DAYS: AR balance = days/90 x quarterly REVENUE — "
  "days from sale to cash in hand. A B2C walk-in / point-of-sale business "
  "collects in ~1-7 days (cards settle in 1-3); a B2B business that "
  "invoices on terms runs 30-60+ days. B2B vs B2C is decisive here.\n"
  "2. INVENTORY DAYS: inventory balance = days/90 x quarterly COGS — days "
  "of cost-of-goods held as stock. Pure services hold none (applicable="
  "false). Fresh / perishable product turns in a few days; apparel and "
  "durable retail often sits 60-120+ days.\n"
  "3. ACCOUNTS PAYABLE DAYS — READ CAREFULLY: the model applies DPO to the "
  "FULL OPERATING-EXPENSE BASE (marketing + R&D + rent + PAYROLL + G&A), "
  "not just vendor purchases. Payroll and rent are paid essentially "
  "immediately, so you must judge the BLENDED days across that whole "
  "base: a shop with net-30 vendor terms on a quarter of its spend has a "
  "blended DPO nearer 7-12 days than 30. Do NOT submit pure vendor terms.\n"
  "4. PREPAID EXPENSES (fraction of quarterly revenue): cash this business "
  "pays in advance and holds as an asset — insurance premiums, annual "
  "software licenses, deposits, prepaid rent. Most small businesses hold "
  "a small, stable 1-5% of quarterly revenue.\n"
  "5. DEFERRED REVENUE (fraction of quarterly revenue) — THE MOST "
  "FAKEABLE NUMBER IN THE MODEL, JUDGE IT HARSHLY: this is cash COLLECTED "
  "BEFORE the work is earned (prepaid memberships, retainers, "
  "subscriptions, annual contracts billed upfront). Assuming customers "
  "prepay frees cash exactly like paying suppliers slower — so you may "
  "credit deferred revenue ONLY to a business whose model genuinely "
  "collects upfront TODAY. A point-of-sale or bill-after-delivery "
  "business (a donut shop, a boutique, a job shop invoicing on delivery) "
  "carries zero or near-zero: mark it applicable=false. Never invent a "
  "prepay model the operator did not describe. Note the revenue LINE is "
  "untouched by this judgment — only the balance and cash timing move; "
  "recognition stays with the revenue trajectory.\n"
  "VIABILITY-BLIND: you are never told whether any plan passes or fails. "
  "Working capital is the easiest place to fake cash into a plan (collect "
  "faster, pay slower, assume prepayment) — you judge only what is REAL "
  "for this business.\n"
  "Q1 IS A FACT where the operator stated actual AR / inventory / AP "
  "balances (given below when stated) — the machine anchors Q1 to the "
  "stated fact; your Q1 should match it and your job is the TRAJECTORY. "
  "Maturation must be modest and operationally explained (a collections "
  "process, tighter buying, negotiated terms), never a step-change.\n"
  "The industry cohort reference is context, not a target: deviate from "
  "it exactly as far as THIS business's model justifies, and say why.\n"
  "Call submit_wc_judgment exactly once."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  operator_wc_facts: Optional[Dict[str, Any]],
  cohort_reference: Optional[Dict[str, Any]],
) -> str:
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
    MARKET_SEMANTICS_PRIMER,
  )
  _compact = dict(compact or {})
  market_reality = {
    k: _compact.pop(k) for k in ("target_market", "market_demand") if k in _compact
  }
  lines: List[str] = []
  lines.append("BUSINESS COMPACT (what this business IS — identity, operations, team):")
  lines.append(json.dumps(_compact, ensure_ascii=False, default=str))
  lines.append("")
  if market_reality:
    lines.append(
      "MARKET REALITY (who the customers are and how they buy — B2B "
      "invoiced terms vs B2C instant payment is the heart of the DSO "
      "judgment):"
    )
    lines.append(json.dumps(market_reality, ensure_ascii=False, default=str))
    lines.append("")
    lines.append(MARKET_SEMANTICS_PRIMER)
    lines.append("")
  if operator_wc_facts:
    lines.append(
      "OPERATOR-STATED WORKING-CAPITAL FACTS (implied Q1 days are computed "
      "from stated balances; where present, Q1 is anchored to the FACT and "
      "is not yours to move — judge the trajectory from it):"
    )
    lines.append(json.dumps(operator_wc_facts, ensure_ascii=False, default=str))
    lines.append("")
  if cohort_reference:
    lines.append(
      "INDUSTRY COHORT REFERENCE (NAICS benchmark days — context only; "
      "this business's actual model governs):"
    )
    lines.append(json.dumps(cohort_reference, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_wc_judgment_once(
  *,
  compact: Dict[str, Any],
  operator_wc_facts: Optional[Dict[str, Any]] = None,
  cohort_reference: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE working-capital-judgment call; return ``{ok, judgment, error}``
  where ``judgment`` = {ar_days|inventory_days|ap_days: {applicable, q1_days,
  q11_days, q20_days, rationale}} (RAW — callers must pass it through
  ``validate_wc_judgment`` before use).

  ``ok=False`` -> the caller keeps the flat NAICS seed (today's behavior)."""
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
        compact=compact,
        operator_wc_facts=operator_wc_facts,
        cohort_reference=cohort_reference,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_wc_judgment"}},
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
  judgment: Dict[str, Any] = {}
  for key in _WC_DRIVER_KEYS:
    entry = parsed.get(key)
    if not isinstance(entry, dict):
      return {"ok": False, "judgment": None, "error": f"driver_missing:{key}"}
    fields = _ANCHOR_FIELDS[_DRIVER_UNIT[key]]
    try:
      normalized: Dict[str, Any] = {
        "applicable": bool(entry.get("applicable")),
        "rationale": str(entry.get("rationale") or "")[:500],
      }
      for field_name, canon in fields:
        normalized[canon] = float(entry.get(field_name))
      judgment[key] = normalized
    except (TypeError, ValueError):
      return {"ok": False, "judgment": None, "error": f"driver_not_numeric:{key}"}
  return {"ok": True, "judgment": judgment, "error": None}


def validate_wc_judgment(
  *,
  judgment: Dict[str, Any],
  implied_q1_days: Optional[Dict[str, Optional[float]]] = None,
  inventory_naics_applicable: Optional[bool] = None,
  stated_balance_positive: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
  """Rail the raw judgment into a validated, executable form.

  Precedence: STATED FACT > NAICS gate (inventory only) > judgment.

  - Every anchor clamped into WC_RAILS (lender-defensible bounds).
  - Q1 FACT OVERRIDE: where an operator-stated balance implies a Q1
    level (days, or fraction of quarterly revenue for prepaid/deferred),
    that fact replaces the judged Q1 anchor (clamped to the rail).
  - STATED-BALANCE APPLICABILITY: a positive stated balance FORCES
    applicable=True regardless of the judgment or the sector gate — the
    operator holding $800 of inventory IS inventory, and zeroing the row
    would both contradict a stated fact and break balance-sheet stub
    continuity (nonzero opening balances may not vanish in live quarters).
  - Inventory NAICS gate: when the sector gate says no inventory and NO
    balance was stated, applicable is FORCED false — a physical-stock
    line for a sector that holds none is a data error, not a judgment.
  - DEFERRED REVENUE HAS NO SECTOR GATE. The old NAICS whitelist
    ({51,52,53,54,62}) zeroed a CORRECT executive call — Apex's gym
    memberships are genuinely billed in advance, judged real by the
    viability-blind executive, killed only because recreation isn't on
    a list. Whether a business truly collects upfront is a question
    about WHAT THE BUSINESS DOES, and the judgment already carries the
    anti-fake guard: it is viability-blind (it zeroed every POS
    business and the doomed shop on reasoning alone, without ever
    seeing a verdict), prompt-hardened ("never invent a prepay model
    the operator did not describe"), railed, and response-locked. The
    sector whitelist survives only in the NO-JUDGMENT fallback seed —
    it never overrides a judgment again.
  - applicable=False -> all anchors 0 (the row seeds to zero).

  Returns {drivers: {key: {applicable,q1,q11,q20,rationale}}, notes: [...]}.
  """
  notes: List[str] = []
  implied = implied_q1_days or {}
  stated = stated_balance_positive or {}
  drivers: Dict[str, Any] = {}
  for key in _WC_DRIVER_KEYS:
    entry = dict((judgment or {}).get(key) or {})
    lo, hi = WC_RAILS[key]
    applicable = bool(entry.get("applicable"))
    has_stated_balance = bool(stated.get(key))
    if (
      key == "inventory_days" and inventory_naics_applicable is False
      and applicable and not has_stated_balance
    ):
      applicable = False
      notes.append(f"{key}_forced_non_applicable_by_naics_gate")
    if has_stated_balance and not applicable:
      applicable = True
      notes.append(f"{key}_forced_applicable_by_stated_balance")
    if not applicable:
      drivers[key] = {
        "applicable": False, "q1": 0.0, "q11": 0.0, "q20": 0.0,
        "rationale": str(entry.get("rationale") or "")[:500],
      }
      continue
    anchors: Dict[str, float] = {}
    for out_key in ("q1", "q11", "q20"):
      try:
        raw = float(entry.get(out_key))
      except (TypeError, ValueError):
        raw = lo
      clamped = max(lo, min(hi, raw))
      if abs(clamped - raw) > 1e-9:
        notes.append(f"{key}.{out_key}_clamped_{raw:.4f}->{clamped:.4f}")
      anchors[out_key] = round(clamped, 6)
    fact = implied.get(key)
    if fact is not None and float(fact) > 0.0:
      fact_clamped = round(max(lo, min(hi, float(fact))), 6)
      if abs(fact_clamped - anchors["q1"]) > 1e-9:
        notes.append(
          f"{key}.q1_overridden_to_stated_fact_{anchors['q1']:.4f}->{fact_clamped:.4f}"
        )
      anchors["q1"] = fact_clamped
    drivers[key] = {
      "applicable": True,
      "q1": anchors["q1"], "q11": anchors["q11"], "q20": anchors["q20"],
      "rationale": str(entry.get("rationale") or "")[:500],
    }
  return {"drivers": drivers, "notes": notes}


def wc_trajectory_per_q(
  anchors: Dict[str, float], *, horizon: int = 20,
) -> List[float]:
  """Linear interpolation Q1 -> Q11 -> Q20 (same executor the cost
  forecast uses): the manager sets three anchors, the machine builds the
  smooth per-quarter path."""
  q1 = float(anchors.get("q1") or 0.0)
  q11 = float(anchors.get("q11") or 0.0)
  q20 = float(anchors.get("q20") or 0.0)
  out: List[float] = []
  for idx in range(max(1, horizon)):
    q = idx + 1
    if q <= 11:
      frac = (q - 1) / 10.0
      val = q1 + (q11 - q1) * frac
    else:
      frac = (q - 11) / 9.0
      val = q11 + (q20 - q11) * frac
    out.append(round(val, 4))
  return out


__all__ = [
  "gpt_author_wc_judgment_once",
  "validate_wc_judgment",
  "wc_trajectory_per_q",
  "WC_RAILS",
  "_LEVER_ID_FOR_DRIVER",
]
