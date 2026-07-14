"""The executive-manager's CASH & CAPITAL-STRUCTURE JUDGMENT.

The cash pass was the last mechanical domain: a flat 1.0-2.0
months-of-opex buffer for every business, funding sources gated by
universal thresholds (chronic-gap >= 5 quarters, rate >= 3%, leverage
>= 0.55), every debt forced to amortize to zero by Q20, posture
defaulting to "balanced", and surplus split by static policy weights.
A seasonal shop, a receivables-heavy law firm, and a project-financed
bioenergy plant all got the same numbers (Cedar_Ridge failed acceptance
on exactly the flat treatment of its project-finance leverage).

Same split as cost / revenue / working capital: the MANAGER judges what
is REAL for this business — how much cash cushion it genuinely needs,
who would actually fund it, what loan structure a lender would extend,
what posture fits its stage, whether surplus should deleverage or
distribute — and the MACHINE keeps every mechanic it already owns
(gap detection, sizing, amortization arithmetic, SBA rates, surplus
caps, post-pass validation). The Python proposer remains the safety
floor and the existing GPT critic still reviews the proposal — now
built FROM the judgment instead of from universal constants.

THE FENCE — cash is the highest fake-viable-risk domain, so this is
the hardest one in the app:
  1. FUNDABILITY, NOT NEED: the judgment may only assume financing a
     REAL lender or investor would extend to THIS business at real
     terms. The test is never "does the plan need it".
  2. STATED FACTS ARE HARD ANCHORS: the operator's stated debt, cash,
     and equity are facts; the operator's selected cash strategy is a
     fact (the judgment fills the posture ONLY when intake left it
     empty). The judgment sets availability and structure — it never
     invents balances and it never sizes amounts (sizing stays with
     the deterministic gap machinery).
  3. VIABILITY-BLIND: the prompt never sees whether the plan passes,
     where cash gaps are, or what any gate needs. It cannot conjure
     funding to close a gap it cannot see.
  4. THE DOCTRINE WALL IS ABSOLUTE: the cash pass may touch debt
     issuance/repayment, owner's capital, other equity, distributions,
     buffer — never revenue, costs, payroll, pricing, capacity. The
     judgment lives entirely inside that wall.
  5. DETERMINISTIC: one locked call (run-once-and-lock); a failed call
     leaves every existing constant exactly as it is today.

WHY THE NEGATIVE TEST HOLDS STRUCTURALLY: the judgment never sizes a
dollar — the machine funds only detected buffer shortfalls, at SBA
rates, with interest drag flowing straight back into the P&L the cash
pass may not touch. A doomed business fails on P&L gates (EBITDA, NI)
that no amount of financing improves; extra debt makes its
interest-burden checks WORSE. Financing availability cannot buy
viability; it only changes how honestly the funding story is told.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

# Python rails — the machine's own believable ranges. The executive
# judges WITHIN these; a rogue judgment cannot promise a 25-year note
# or a zero cash cushion.
CASH_RAILS: Dict[str, Any] = {
  "buffer_months": (0.5, 4.0),
  "ceiling_months_max": 6.0,
  "ceiling_min_spread": 0.5,
  "debt_term_quarters": (4, 40),
}

_POSTURES = ("preserve_cash", "balanced", "shareholder_return")
_SURPLUS_PRIORITIES = ("deleverage_first", "distribute_ok")


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_cash_judgment",
    "description": (
      "Submit the cash & capital-structure judgment for this business. "
      "Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "cash_buffer": {
          "type": "object",
          "properties": {
            "buffer_months": {
              "type": "number",
              "description": (
                "Months of operating expenses THIS business genuinely needs "
                "as its minimum cash cushion (its revenue volatility, "
                "seasonality, receivable timing, contract cover)."
              ),
            },
            "ceiling_months": {
              "type": "number",
              "description": (
                "Months of opex above which cash is genuinely surplus for "
                "this business (deployable to debt paydown/distributions)."
              ),
            },
            "rationale": {"type": "string"},
          },
          "required": ["buffer_months", "ceiling_months", "rationale"],
        },
        "funding_access": {
          "type": "object",
          "properties": {
            "debt_available": {
              "type": "boolean",
              "description": (
                "Would a REAL lender (bank / SBA) extend term debt to this "
                "business at market terms today?"
              ),
            },
            "owner_equity_available": {
              "type": "boolean",
              "description": (
                "Could the owner(s) realistically contribute additional "
                "capital at this business's scale?"
              ),
            },
            "outside_equity_available": {
              "type": "boolean",
              "description": (
                "Does this business's TYPE and STAGE demonstrably attract "
                "outside investors (VC/angel/strategic)? A main-street shop "
                "does not; a scaled software company does."
              ),
            },
            "rationale": {"type": "string"},
          },
          "required": [
            "debt_available", "owner_equity_available",
            "outside_equity_available", "rationale",
          ],
        },
        "debt_structure": {
          "type": "object",
          "properties": {
            "term_quarters": {
              "type": "integer",
              "description": (
                "The loan term (in quarters) a real lender would extend to "
                "this business for its debt load: short working-capital "
                "notes ~8-12, standard SBA term ~28-40, asset-backed / "
                "project finance toward 40."
              ),
            },
            "rationale": {"type": "string"},
          },
          "required": ["term_quarters", "rationale"],
        },
        "capital_posture": {
          "type": "object",
          "properties": {
            "posture": {
              "type": "string",
              "enum": list(_POSTURES),
              "description": (
                "The capital posture coherent with this business's stage "
                "and leverage. APPLIED ONLY when the operator did not "
                "select one at intake — the operator's selection is a fact."
              ),
            },
            "rationale": {"type": "string"},
          },
          "required": ["posture", "rationale"],
        },
        "surplus_deployment": {
          "type": "object",
          "properties": {
            "priority": {
              "type": "string",
              "enum": list(_SURPLUS_PRIORITIES),
              "description": (
                "deleverage_first: surplus pays down debt before any "
                "distribution (right for a leveraged business). "
                "distribute_ok: the strategy's normal split applies (right "
                "for a clean balance sheet)."
              ),
            },
            "rationale": {"type": "string"},
          },
          "required": ["priority", "rationale"],
        },
      },
      "required": [
        "cash_buffer", "funding_access", "debt_structure",
        "capital_posture", "surplus_deployment",
      ],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER judging this business's CASH AND CAPITAL "
  "STRUCTURE — the cushion it truly needs, who would actually fund it, "
  "the loan structure a real lender would extend, the posture that fits "
  "its stage, and what genuine surplus should do — the way a competent "
  "CFO would defend the funding story to a small-business LENDER.\n"
  "THE ONE RULE ABOVE ALL — FUNDABILITY, NOT NEED: every call you make "
  "must pass the test 'would a real lender or investor extend THIS, to "
  "THIS business, at these terms?' — never 'would it help'. You are "
  "never told whether any plan passes, where its cash runs thin, or "
  "what any check requires — judge the business, not a plan's needs.\n"
  "1. CASH BUFFER (months of operating expenses): a steady contracted "
  "operation (utility PPA, enterprise subscriptions) can run leaner; a "
  "seasonal or walk-in business needs more cushion; thin-margin "
  "businesses with lumpy receivables need the most. Judge THIS "
  "business's revenue volatility, collection timing, and contract "
  "cover. The ceiling is where cash is genuinely idle for this "
  "business, not a hoarding target.\n"
  "2. FUNDING ACCESS: judge who would ACTUALLY provide capital. Debt: "
  "does this business have the collateral, coverage, and history a "
  "bank or SBA lender requires? Owner equity: can owners of a business "
  "this size realistically add capital? Outside equity: ONLY business "
  "types and stages that demonstrably attract investors — a scaled or "
  "high-growth software/IP business does; a donut shop, a solo "
  "practice, a main-street retailer does NOT, no matter how much cash "
  "would help. Never invent an investor the business could not find.\n"
  "3. DEBT STRUCTURE: the term a real lender would write for this "
  "business's profile — short notes for working capital, standard SBA "
  "terms for main-street operations, longer asset-backed/project terms "
  "only where hard assets or contracted revenue secure them.\n"
  "4. CAPITAL POSTURE: preserve_cash / balanced / shareholder_return — "
  "which is COHERENT for this stage and leverage? (Applied only when "
  "the operator did not select one; their selection is a fact.)\n"
  "5. SURPLUS: a leveraged business pays debt down before paying "
  "anyone out; a clean business may distribute true surplus. Say which "
  "this is and why.\n"
  "The machine keeps all sizing, timing, rate (SBA policy), and "
  "validation mechanics — you set the judgment parameters it executes "
  "within. Call submit_cash_judgment exactly once."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  stated_facts: Optional[Dict[str, Any]],
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
      "MARKET REALITY (revenue stability and customer profile inform the "
      "buffer and the funding story):"
    )
    lines.append(json.dumps(market_reality, ensure_ascii=False, default=str))
    lines.append("")
    lines.append(MARKET_SEMANTICS_PRIMER)
    lines.append("")
  if stated_facts:
    lines.append(
      "OPERATOR-STATED CAPITAL FACTS (hard anchors — these balances and "
      "any selected strategy are facts, not levers; judge structure and "
      "access around them):"
    )
    lines.append(json.dumps(stated_facts, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_cash_judgment_once(
  *,
  compact: Dict[str, Any],
  stated_facts: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE cash-judgment call; return ``{ok, judgment, error}`` (RAW —
  callers must pass it through ``validate_cash_judgment``).

  ``ok=False`` -> every existing mechanical constant stands (today's
  exact behavior)."""
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
        compact=compact, stated_facts=stated_facts,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_cash_judgment"}},
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
  for key in ("cash_buffer", "funding_access", "debt_structure", "capital_posture", "surplus_deployment"):
    if not isinstance(parsed.get(key), dict):
      return {"ok": False, "judgment": None, "error": f"decision_missing:{key}"}
  return {"ok": True, "judgment": parsed, "error": None}


def validate_cash_judgment(
  *,
  judgment: Dict[str, Any],
  operator_selected_posture: bool,
) -> Dict[str, Any]:
  """Rail the raw judgment into a validated, executable form.

  - Buffer / ceiling clamped into CASH_RAILS; ceiling always at least
    ``ceiling_min_spread`` above the buffer.
  - Debt term clamped into [4, 40] quarters (integer).
  - Posture coerced to a known value; marked apply=False when the
    operator selected a strategy at intake (stated fact wins — the
    judged posture is then recorded as a coherence note only).
  - Surplus priority coerced to a known value.

  Returns {buffer_months, ceiling_months, funding_access{...},
  debt_term_quarters, posture, posture_applies, surplus_priority,
  rationales{...}, notes[...]}.
  """
  notes: List[str] = []
  j = judgment or {}

  buf = j.get("cash_buffer") or {}
  lo, hi = CASH_RAILS["buffer_months"]
  try:
    buffer_months = float(buf.get("buffer_months"))
  except (TypeError, ValueError):
    buffer_months = lo
  clamped = max(lo, min(hi, buffer_months))
  if abs(clamped - buffer_months) > 1e-9:
    notes.append(f"buffer_months_clamped_{buffer_months:.2f}->{clamped:.2f}")
  buffer_months = round(clamped, 2)
  try:
    ceiling_months = float(buf.get("ceiling_months"))
  except (TypeError, ValueError):
    ceiling_months = buffer_months + CASH_RAILS["ceiling_min_spread"]
  ceil_lo = buffer_months + CASH_RAILS["ceiling_min_spread"]
  ceil_hi = CASH_RAILS["ceiling_months_max"]
  clamped_c = max(ceil_lo, min(ceil_hi, ceiling_months))
  if abs(clamped_c - ceiling_months) > 1e-9:
    notes.append(f"ceiling_months_clamped_{ceiling_months:.2f}->{clamped_c:.2f}")
  ceiling_months = round(clamped_c, 2)

  fa = j.get("funding_access") or {}
  funding_access = {
    "debt_available": bool(fa.get("debt_available")),
    "owner_equity_available": bool(fa.get("owner_equity_available")),
    "outside_equity_available": bool(fa.get("outside_equity_available")),
  }

  ds = j.get("debt_structure") or {}
  t_lo, t_hi = CASH_RAILS["debt_term_quarters"]
  try:
    term = int(round(float(ds.get("term_quarters"))))
  except (TypeError, ValueError):
    term = t_hi
  clamped_t = max(t_lo, min(t_hi, term))
  if clamped_t != term:
    notes.append(f"debt_term_clamped_{term}->{clamped_t}")
  term = clamped_t

  cp = j.get("capital_posture") or {}
  posture = str(cp.get("posture") or "").strip().lower()
  if posture not in _POSTURES:
    posture = "balanced"
    notes.append("posture_coerced_to_balanced")
  posture_applies = not bool(operator_selected_posture)
  if operator_selected_posture:
    notes.append("posture_not_applied_operator_selection_is_a_fact")

  sd = j.get("surplus_deployment") or {}
  priority = str(sd.get("priority") or "").strip().lower()
  if priority not in _SURPLUS_PRIORITIES:
    priority = "distribute_ok"
    notes.append("surplus_priority_coerced_to_distribute_ok")

  return {
    "buffer_months": buffer_months,
    "ceiling_months": ceiling_months,
    "funding_access": funding_access,
    "debt_term_quarters": term,
    "posture": posture,
    "posture_applies": posture_applies,
    "surplus_priority": priority,
    "rationales": {
      "cash_buffer": str(buf.get("rationale") or "")[:500],
      "funding_access": str(fa.get("rationale") or "")[:500],
      "debt_structure": str(ds.get("rationale") or "")[:500],
      "capital_posture": str(cp.get("rationale") or "")[:500],
      "surplus_deployment": str(sd.get("rationale") or "")[:500],
    },
    "notes": notes,
  }


def cash_judgment_from_model_input(
  model_input_json: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """Read the validated judgment stamped at authoring time. Returns None
  when absent (every consumer then keeps today's mechanical constants)."""
  if not isinstance(model_input_json, dict):
    return None
  solver_input = model_input_json.get("solver_input")
  if not isinstance(solver_input, dict):
    return None
  judgment = solver_input.get("cash_judgment")
  return judgment if isinstance(judgment, dict) and judgment.get("funding_access") else None


__all__ = [
  "gpt_author_cash_judgment_once",
  "validate_cash_judgment",
  "cash_judgment_from_model_input",
  "CASH_RAILS",
]
