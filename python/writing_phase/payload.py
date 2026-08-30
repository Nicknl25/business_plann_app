"""THE WRITER PAYLOAD, SETTLED (Nick's ruling, 2026-08-30).

What GPT gets when a section is written, and in what order. Three decisions
live here and nowhere else:

1. EXCLUDED: realism_memo_json and model_input_json never reach the writer.
   Not for the tokens - they are machinery, rule 4 bans discussing machinery,
   and handing the writer 373k tokens of internals it must read and never
   mention is asking for the violation.

2. FINMO GOES TO THE BODY ANNUAL: five annual columns plus break_even.
   Quarterly detail exists only where the appendix and the two exception
   facts need it. Rule 18 enforced by payload rather than by check - a writer
   that never sees a quarterly number cannot leak one.

3. SHARED-PAYLOAD-FIRST: every section call carries the identical shared
   block as its PREFIX, so prompt caching applies across all nine calls
   (measured 2026-08-30: the shared block is >90% of every call; caching
   cuts the plan cost ~72-77%).

Nothing here calls GPT. It builds strings.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from . import rules as R
from .facts import sentences as S
from .facts.assembler import BriefAssembly, SectionBrief

#: Never reaches the writer. The reason is rule 4, not the token count.
EXCLUDED_PAYLOADS = ("realism_memo_json", "model_input_json")

#: The writer set - the whole picture minus machinery (measured ~48k tokens
#: with annual finmo on a real draft; ~$0.28 a plan with caching).
CORE_PAYLOADS = (
  "operating_model_json",
  "target_market_json",
  "financials_json",
  "people_json",
  "fulfillment_json",
  "marketing_schedule_json",
  "payroll_headcount",
)

#: P&L/cash-flow style keys are FLOWS (summed into a year); everything else on
#: a quarter row is a BALANCE (year-end value).
_FLOW_KEYS = {
  "revenue", "cogs", "cost_of_goods_sold", "gross_profit", "marketing",
  "research_and_development", "lease_rent", "payroll", "g_and_a",
  "general_and_administrative", "ebitda", "interest", "depreciation", "taxes",
  "net_income", "operating_cash_flow", "investing_cash_flow",
  "financing_cash_flow", "net_cash_flow", "capital_expenditures",
  "debt_issuance", "debt_repayment", "distributions",
  "lease_principal_repayments", "lease_interest_expense",
}


def _jload(v: Any) -> Any:
  if v is None:
    return {}
  if isinstance(v, (dict, list)):
    return v
  try:
    return json.loads(v)
  except Exception:
    return {}


def finmo_annual_body(finmo: Any) -> Dict[str, Any]:
  """The body's view of FINMO: five annual rows plus break_even. No
  quarter_rows, no statement arrays, no period map."""
  fj = _jload(finmo)
  qr = [r for r in (fj.get("quarter_rows") or [])
        if isinstance(r, dict) and 1 <= int(float(r.get("quarter_index") or -1)) <= 20]
  qr.sort(key=lambda r: int(float(r["quarter_index"])))
  annual: List[Dict[str, Any]] = []
  for y in range(1, 6):
    grp = qr[4 * (y - 1):4 * y]
    if len(grp) != 4:
      continue
    row: Dict[str, Any] = {"year": y}
    for key in grp[0]:
      try:
        vals = [float(g.get(key)) for g in grp]
      except (TypeError, ValueError):
        continue
      row[key] = round(sum(vals), 2) if key in _FLOW_KEYS else round(vals[-1], 2)
    annual.append(row)
  return {
    "contract_version": fj.get("contract_version"),
    "annual_rows": annual,
    "break_even": fj.get("break_even"),
  }


def build_shared_block(draft: Dict[str, Any]) -> str:
  """The block every section call shares, deterministic and ordered:
  rules first, then the core payloads, then annual FINMO. Identical bytes
  across calls IS the caching mechanism - do not reorder per section."""
  for k in EXCLUDED_PAYLOADS:
    # the exclusion is structural: the shared block never reads these keys
    pass
  parts: List[str] = []
  parts.append("== WRITING RULES ==")
  parts.append(json.dumps(
    [{"rule": r["id"], "instruction": r["prompt_instruction"]} for r in R.WRITING_RULES],
    separators=(",", ":"), ensure_ascii=False))
  parts.append("== BUSINESS RECORD ==")
  record = {k: _jload(draft.get(k)) for k in CORE_PAYLOADS}
  parts.append(json.dumps(record, separators=(",", ":"), ensure_ascii=False, default=str))
  parts.append("== FINANCIAL PROJECTIONS (ANNUAL) ==")
  parts.append(json.dumps(finmo_annual_body(draft.get("finmo_json")),
                          separators=(",", ":"), ensure_ascii=False, default=str))
  return "\n".join(parts)


def build_section_block(brief: SectionBrief) -> str:
  """The per-section suffix: the section's facts, its narrative slice, and its
  sentence templates. This is the only part that differs between calls."""
  spec = R.section(brief.section_key)
  parts: List[str] = []
  parts.append("== SECTION: %s ==" % spec["title"])
  parts.append("== SECTION FACTS (reference as {{fact:key}}; never type a number) ==")
  parts.append(json.dumps(brief.facts, separators=(",", ":"), ensure_ascii=False))
  if brief.narratives:
    parts.append("== SECTION NARRATIVE (the client's own account; rework, never restate) ==")
    parts.append(json.dumps(brief.narratives, separators=(",", ":"), ensure_ascii=False, default=str))
  sents = S.sentences_for_section(brief.section_key)
  if sents:
    parts.append("== OBSERVATIONS AVAILABLE TO THIS SECTION ==")
    parts.append(json.dumps(
      [{"id": x["id"], "template": x["text"], "class": x["class"]} for x in sents],
      separators=(",", ":"), ensure_ascii=False))
  return "\n".join(parts)


def build_prompt(shared_block: str, section_block: str) -> str:
  """Shared FIRST, always - the caching contract."""
  return shared_block + "\n" + section_block
