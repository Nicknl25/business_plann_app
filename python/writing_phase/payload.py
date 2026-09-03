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
  "financials_year1_json",
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


def client_transcript(draft: Dict[str, Any]) -> List[str]:
  """The client's verbatim turns - the only place their voice exists. Shared
  block (cached once) rather than a per-section narrative grant, because
  three sections draw on it. Absent on replay-built drafts; degrades to []."""
  msgs = _jload(draft.get("messages_json"))
  if not isinstance(msgs, list):
    return []
  return [str(m.get("content") or "") for m in msgs
          if isinstance(m, dict) and m.get("role") == "user" and str(m.get("content") or "").strip()]


def build_shared_block(draft: Dict[str, Any], *, workbook_stamp: Optional[Dict[str, Any]] = None) -> str:
  """The block every section call shares, deterministic and ordered:
  rules, the workbook manifest, the business record, the client's verbatim
  transcript, then annual FINMO. Identical bytes across a draft's nine calls
  IS the caching mechanism - do not reorder per section. The stamp (filename,
  run id) is per-draft and therefore safely inside the shared block."""
  for k in EXCLUDED_PAYLOADS:
    # the exclusion is structural: the shared block never reads these keys
    pass
  parts: List[str] = []
  parts.append("== WRITING RULES ==")
  parts.append(json.dumps(
    [{"rule": r["id"], "instruction": r["prompt_instruction"]} for r in R.WRITING_RULES],
    separators=(",", ":"), ensure_ascii=False))
  parts.append("== THE ACCOMPANYING WORKBOOK ==")
  parts.append(R.WORKBOOK_REFERENCE_INSTRUCTION)
  manifest: Dict[str, Any] = {"sheets": list(R.WORKBOOK_MANIFEST)}
  if workbook_stamp:
    manifest["delivered"] = workbook_stamp
  parts.append(json.dumps(manifest, separators=(",", ":"), ensure_ascii=False, default=str))
  parts.append("== BUSINESS RECORD ==")
  record = {k: _jload(draft.get(k)) for k in CORE_PAYLOADS}
  parts.append(json.dumps(record, separators=(",", ":"), ensure_ascii=False, default=str))
  voice = client_transcript(draft)
  if voice:
    parts.append("== THE CLIENT'S OWN WORDS (verbatim intake transcript) ==")
    parts.append(json.dumps(voice, separators=(",", ":"), ensure_ascii=False))
  parts.append("== FINANCIAL PROJECTIONS (ANNUAL) ==")
  parts.append(json.dumps(finmo_annual_body(draft.get("finmo_json")),
                          separators=(",", ":"), ensure_ascii=False, default=str))
  return "\n".join(parts)


def build_section_block(brief: SectionBrief,
                        exclude_sentence_ids: Tuple[str, ...] = (),
                        exclude_fact_keys: Tuple[str, ...] = ()) -> str:
  """The per-section suffix: the section's facts, its narrative slice, and its
  sentence templates. This is the only part that differs between calls.
  `exclude_sentence_ids` drops observations the AUTHOR rules out structurally
  (the tenure age-pick, Nick 2026-09-01) - a writer that never sees the wrong
  tenure line cannot use it, the same shape as rule 18's payload enforcement."""
  spec = R.section(brief.section_key)
  parts: List[str] = []
  parts.append("== SECTION: %s ==" % spec["title"])
  parts.append("== SECTION FACTS (reference as {{fact:key}}; never type a number) ==")
  # exclude_fact_keys prunes facts the author ruled out (the wrong-age tenure
  # rate, 2026-09-02) - filtering the observation alone left the FACT in the
  # brief, and the writer quoted a first-year exit rate on a 7th-year business
  facts = {k: v for k, v in brief.facts.items() if k not in set(exclude_fact_keys)}
  parts.append(json.dumps(facts, separators=(",", ":"), ensure_ascii=False))
  if brief.narratives:
    parts.append("== SECTION NARRATIVE (the client's own account; rework, never restate) ==")
    parts.append(json.dumps(brief.narratives, separators=(",", ":"), ensure_ascii=False, default=str))
  # NO SENTENCE TEMPLATES (Nick 2026-09-02): "a writer given templates fills
  # them." The writer gets the facts each observation must put on the page;
  # the sentences are its job. Templates stay in sentences.py as the
  # catalogue's derivation record only.
  from .facts.assembler import IDENTITY_KEYS
  sents = [x for x in S.sentences_for_section(brief.section_key)
           if x["id"] not in set(exclude_sentence_ids)]
  cover = []
  for x in sents:
    keys = [k for k in x["needs"] if k not in IDENTITY_KEYS and k in facts]
    if keys:
      cover.append({"id": x["id"],
                    "facts": x.get("floor_required") or keys})
  if cover:
    parts.append("== MUST COVER (each entry's facts must appear on the page; "
                 "how is yours) ==")
    parts.append(json.dumps(cover, separators=(",", ":"), ensure_ascii=False))
  return "\n".join(parts)


def build_prompt(shared_block: str, section_block: str) -> str:
  """Shared FIRST, always - the caching contract."""
  return shared_block + "\n" + section_block
