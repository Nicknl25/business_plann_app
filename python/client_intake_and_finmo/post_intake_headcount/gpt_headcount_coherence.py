"""The executive-manager's HEADCOUNT-COHERENCE judgment (right-sizing).

The labor system can scale a team UP (hires as revenue grows) and shave
the payroll ratio DOWN to an executive floor — but it could not reason
"this business is OVERSTAFFED for its revenue; a coherent version runs
leaner." Understory exposed the gap: 4 people / $130k payroll on $298k
of specialty-farm revenue is genuinely overstaffed, and the only lever
was a 44%→40% ratio shave. A real turnaround advisor right-sizes an
overstaffed team — that is honest planning, not fake viability.

This module is PURELY ADDITIVE: the labor-model judgment
(revenue_scales_with_labor), OEWS wage floors, part-time hourly-rate
handling, the payroll trial, and stated-payroll anchoring are all
untouched. When the judgment does not fire, nothing anywhere changes.

THE FENCE — headcount cuts are the classic fake-viable move, so:
  1. RIGHT-SIZE TO COHERENCE, NEVER UNDERSTAFF TO PASS: the judgment
     reasons what a real operator RUNS at this revenue — it never sees
     the verdict, the gap, or what passing requires (viability-blind).
  2. A correctly-staffed or lean business MUST come back
     overstaffed=false and is left completely alone (the grocer's 70
     checkout staff, the manufacturer's floor, a lean 2-person shop).
  3. Python rails: the right-sized payroll may never cut more than 60%
     of the stated total, and never below the owner's own stated wage —
     the owner is never cut; a doomed-but-lean business cannot be
     "right-sized" into viability because there is nothing to trim.
  4. LENDER-DEFENSIBLE: the coherent structure must be one a lender
     believes ("a specialty farm at this revenue runs on ~2 people").
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1"
_DEFAULT_TIMEOUT_SECONDS = 60.0

# Python rails — right-sizing bounds the machine enforces regardless of
# what the judgment says.
HEADCOUNT_COHERENCE_RAILS: Dict[str, Any] = {
  # The right-sized annual payroll may not cut more than this fraction
  # of the stated total (understaffing-to-pass fence).
  "max_cut_fraction": 0.60,
}


def _resolve_model(model: Optional[str]) -> str:
  if model:
    return str(model)
  return (os.getenv("OPENAI_MODEL") or "").strip() or _DEFAULT_MODEL


_SUBMIT_TOOL: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "submit_headcount_coherence",
    "description": (
      "Submit the headcount-coherence judgment for this business. "
      "Call exactly once."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "overstaffed": {
          "type": "boolean",
          "description": (
            "true ONLY when the stated team is genuinely INCOHERENT with "
            "the business's revenue/scale — more people than a competent "
            "operator of this exact business would run. A lean or "
            "appropriately-staffed team is false, full stop."
          ),
        },
        "coherent_annual_payroll": {
          "type": "number",
          "description": (
            "When overstaffed: the total annual payroll (owner included) "
            "a coherent version of THIS business runs at THIS revenue. "
            "Must be a structure a real operator would actually run and "
            "a lender would believe. Ignored when overstaffed=false."
          ),
        },
        "coherent_structure": {
          "type": "string",
          "description": (
            "When overstaffed: the right-sized team in plain words "
            "(e.g. 'owner-cultivator plus one part-time harvest hand')."
          ),
        },
        "rationale": {
          "type": "string",
          "description": (
            "The lender defense: why the stated team is or is not "
            "coherent with the revenue, reasoned from what the work "
            "actually requires at this scale (3-4 sentences)."
          ),
        },
      },
      "required": ["overstaffed", "coherent_annual_payroll", "coherent_structure", "rationale"],
    },
  },
}


_SYSTEM_PROMPT = (
  "You are the EXECUTIVE-MANAGER judging HEADCOUNT COHERENCE for one "
  "specific business: is the stated team appropriate for THIS business "
  "at THIS revenue, or genuinely overstaffed?\n"
  "THE FENCE: you are told NOTHING about whether any plan passes "
  "anything, and you must never reason toward an outcome. You judge "
  "purely from what the WORK requires at this scale — like a seasoned "
  "operator or turnaround advisor walking the floor.\n"
  "HOW TO JUDGE:\n"
  "1. WHAT DOES THE WORK ACTUALLY TAKE? Reason from the operation: how "
  "many hands does this revenue's worth of production, service, and "
  "administration genuinely need, in this business model? Use "
  "revenue-per-employee sanity for the TYPE (a checkout-lane grocer "
  "legitimately runs ~$200k/employee; a professional practice far "
  "more; hand-cultivation less — judge the type, not a universal bar).\n"
  "2. OVERSTAFFED MEANS INCOHERENT, NOT MERELY EXPENSIVE: a team that "
  "is busy and necessary is NOT overstaffed even if payroll is a heavy "
  "ratio — labor-intensive businesses are allowed to be labor-"
  "intensive. Overstaffed means a competent operator at this revenue "
  "would genuinely run FEWER people (idle capacity, duplicated roles, "
  "staffing built for a scale the revenue does not support).\n"
  "3. WHEN IN DOUBT, THE TEAM STANDS: right-sizing a business that is "
  "actually staffed to its work is the classic dishonest-plan move. "
  "Return overstaffed=false unless the incoherence is plain.\n"
  "4. THE COHERENT STRUCTURE MUST BE RUNNABLE: the right-sized team "
  "must actually be able to operate the business at the stated revenue "
  "(the owner is always retained; someone has to do the work). Describe "
  "it concretely and defend it as you would to a lender.\n"
  "Call submit_headcount_coherence exactly once."
)


def _build_user_prompt(
  *,
  compact: Dict[str, Any],
  stated_staffing: Dict[str, Any],
) -> str:
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
    MARKET_SEMANTICS_PRIMER,
  )
  _compact = dict(compact or {})
  market_reality = {
    k: _compact.pop(k) for k in ("target_market", "market_demand") if k in _compact
  }
  lines: List[str] = []
  lines.append("BUSINESS COMPACT (what this business IS — judge the work from this):")
  lines.append(json.dumps(_compact, ensure_ascii=False, default=str))
  lines.append("")
  if market_reality:
    lines.append("MARKET REALITY (the scale the revenue actually supports):")
    lines.append(json.dumps(market_reality, ensure_ascii=False, default=str))
    lines.append("")
    lines.append(MARKET_SEMANTICS_PRIMER)
    lines.append("")
  lines.append(
    "STATED STAFFING FACTS (the operator's team today — judge whether "
    "this team is coherent with this revenue):"
  )
  lines.append(json.dumps(stated_staffing, ensure_ascii=False, default=str))
  return "\n".join(lines)


def gpt_author_headcount_coherence_once(
  *,
  compact: Dict[str, Any],
  stated_staffing: Dict[str, Any],
  model: Optional[str] = None,
  seed: int = 1733,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  _http: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Make ONE headcount-coherence call; return ``{ok, judgment, error}``
  (RAW — callers must pass it through ``validate_headcount_coherence``).

  ``ok=False`` -> the stated team stands untouched (today's exact
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
        compact=compact, stated_staffing=stated_staffing,
      )},
    ],
    "tools": [_SUBMIT_TOOL],
    "tool_choice": {"type": "function", "function": {"name": "submit_headcount_coherence"}},
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

  if not isinstance(parsed, dict) or "overstaffed" not in parsed:
    return {"ok": False, "judgment": None, "error": "no_judgment_in_tool_call"}
  return {"ok": True, "judgment": parsed, "error": None}


def validate_headcount_coherence(
  *,
  judgment: Dict[str, Any],
  stated_annual_payroll: float,
  stated_owner_annual_wage: float,
) -> Dict[str, Any]:
  """Rail the raw judgment into a validated, executable form.

  - Inert (``applies=False``) unless overstaffed=true AND the coherent
    payroll is genuinely below the stated total.
  - The coherent payroll is floored at (1 - max_cut_fraction) x stated
    (never cut more than 60% — the understaffing-to-pass fence) AND at
    the owner's own stated wage (the owner is never cut).

  Returns {applies, overstaffed, coherent_annual_payroll,
  stated_annual_payroll, right_size_factor, coherent_structure,
  rationale, notes[...]} where right_size_factor = coherent / stated.
  """
  notes: List[str] = []
  j = judgment or {}
  stated = max(0.0, float(stated_annual_payroll or 0.0))
  owner_wage = max(0.0, float(stated_owner_annual_wage or 0.0))
  overstaffed = bool(j.get("overstaffed"))
  try:
    coherent = float(j.get("coherent_annual_payroll"))
  except (TypeError, ValueError):
    coherent = stated
  if coherent != coherent:  # NaN
    coherent = stated

  applies = bool(overstaffed and stated > 0 and coherent < stated - 0.5)
  if applies:
    floor = max(
      stated * (1.0 - float(HEADCOUNT_COHERENCE_RAILS["max_cut_fraction"])),
      owner_wage,
    )
    if coherent < floor:
      notes.append(f"coherent_payroll_floored_{coherent:.0f}->{floor:.0f}")
      coherent = floor
    if coherent >= stated - 0.5:
      applies = False
      notes.append("right_sizing_inert_after_rails")
  else:
    coherent = stated

  return {
    "applies": applies,
    "overstaffed": overstaffed,
    "coherent_annual_payroll": round(float(coherent), 2),
    "stated_annual_payroll": round(float(stated), 2),
    "stated_owner_annual_wage": round(float(owner_wage), 2),
    "right_size_factor": round(float(coherent) / float(stated), 4) if stated > 0 else 1.0,
    "coherent_structure": str(j.get("coherent_structure") or "")[:240],
    "rationale": str(j.get("rationale") or "")[:600],
    "notes": notes,
  }


def headcount_coherence_from_model_input(
  model_input_json: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """Read the validated judgment stamped at authoring time. Returns None
  when absent or inert (every consumer then leaves the team untouched)."""
  if not isinstance(model_input_json, dict):
    return None
  solver_input = model_input_json.get("solver_input")
  if not isinstance(solver_input, dict):
    return None
  judgment = solver_input.get("headcount_coherence")
  if not isinstance(judgment, dict) or not judgment.get("applies"):
    return None
  return judgment


__all__ = [
  "gpt_author_headcount_coherence_once",
  "validate_headcount_coherence",
  "headcount_coherence_from_model_input",
  "HEADCOUNT_COHERENCE_RAILS",
]
