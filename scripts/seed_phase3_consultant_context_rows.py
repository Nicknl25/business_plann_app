"""Seed rows for the three Phase 3 consultant contracts in
post_intake_gpt_context_lookup.

Idempotent: INSERT ... ON DUPLICATE KEY UPDATE keyed by
(contract_name, context_key, include_phase).

Run from repo root:
  python scripts/seed_phase3_consultant_context_rows.py
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, os.path.join(ROOT, "python"))

from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402


CONTRACTS = [
  ("post_intake_band_shaping_consultant", "band_shaping"),
  ("post_intake_target_shaping_consultant", "target_shaping"),
  ("post_intake_conflict_adjudication_consultant", "conflict_adjudication"),
]


def _row(
  *,
  contract_name: str,
  context_key: str,
  context_group: str,
  source_kind: str,
  source_path: str,
  transform_kind: str,
  include_phase: str,
  required: int,
  include_in_prompt: int,
  max_items: Any = None,
  max_chars: Any = None,
  failure_code: str,
  notes: str = "",
) -> Dict[str, Any]:
  return {
    "contract_name": contract_name,
    "context_key": context_key,
    "context_group": context_group,
    "source_kind": source_kind,
    "source_path": source_path,
    "transform_kind": transform_kind,
    "include_phase": include_phase,
    "required": required,
    "include_in_prompt": include_in_prompt,
    "max_items": max_items,
    "max_chars": max_chars,
    "failure_code": failure_code,
    "context_status": "active",
    "notes": notes,
  }


def _common_rows(contract_name: str, include_phase: str) -> List[Dict[str, Any]]:
  fc = lambda key: f"{contract_name}_{key}_context_invalid"
  return [
    _row(
      contract_name=contract_name,
      context_key="__openai_request_budget__",
      context_group="budget",
      source_kind="policy",
      source_path="",
      transform_kind="request_char_budget",
      include_phase=include_phase,
      required=1,
      include_in_prompt=0,
      max_chars=180000,
      failure_code=f"{contract_name}_payload_budget_exceeded",
      notes="Char budget cap for the consultant request payload.",
    ),
    _row(
      contract_name=contract_name,
      context_key="draft_id",
      context_group="trace",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=0,
      failure_code=fc("draft_id"),
    ),
    _row(
      contract_name=contract_name,
      context_key="planning_run_id",
      context_group="trace",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=0,
      failure_code=fc("planning_run_id"),
    ),
    _row(
      contract_name=contract_name,
      context_key="business_identity",
      context_group="business_world",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=1,
      include_in_prompt=1,
      failure_code=fc("business_identity"),
      notes="Raw classification signals: business_type, NAICS 6/2, stage, model, primary offering summary.",
    ),
    _row(
      contract_name=contract_name,
      context_key="business_descriptors",
      context_group="business_world",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=1,
      failure_code=fc("business_descriptors"),
      notes="Narrative descriptors: growth intent, competitive context, operating model, founder intent.",
    ),
    _row(
      contract_name=contract_name,
      context_key="financial_snapshot",
      context_group="financials",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=1,
      include_in_prompt=1,
      failure_code=fc("financial_snapshot"),
      notes="Current-state raw numbers: revenue, COGS, AR/AP/Inventory balances, debt, cash, etc.",
    ),
    _row(
      contract_name=contract_name,
      context_key="year1_projection",
      context_group="financials",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=1,
      include_in_prompt=1,
      failure_code=fc("year1_projection"),
      notes="Year-1 projection numbers from financials_year1_json.",
    ),
    _row(
      contract_name=contract_name,
      context_key="planning_mode_context",
      context_group="policy",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=1,
      include_in_prompt=1,
      failure_code=fc("planning_mode_context"),
      notes="planning_mode (turnaround/normalize/rebalance) and reason.",
    ),
    _row(
      contract_name=contract_name,
      context_key="business_profile_for_cohort",
      context_group="business_world",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=1,
      include_in_prompt=1,
      failure_code=fc("business_profile_for_cohort"),
      notes="Compact cohort key: naics_6, target_annual_revenue, stage, business_model.",
    ),
    _row(
      contract_name=contract_name,
      context_key="target_market_signals",
      context_group="business_world",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=1,
      failure_code=fc("target_market_signals"),
      notes="Raw target_market_json (customers, geography, ICP).",
    ),
    _row(
      contract_name=contract_name,
      context_key="people_capability_signals",
      context_group="business_world",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=1,
      failure_code=fc("people_capability_signals"),
      notes="Raw people_json (roles, headcount intent).",
    ),
    _row(
      contract_name=contract_name,
      context_key="fulfillment_model_signals",
      context_group="business_world",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=1,
      failure_code=fc("fulfillment_model_signals"),
      notes="Raw fulfillment_json (delivery / service model).",
    ),
    _row(
      contract_name=contract_name,
      context_key="marketing_model_signals",
      context_group="business_world",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=1,
      failure_code=fc("marketing_model_signals"),
      notes="Raw marketing_model_json (channels, acquisition motion).",
    ),
    _row(
      contract_name=contract_name,
      context_key="stage_ramp_contract",
      context_group="model_input",
      source_kind="runtime",
      source_path="",
      transform_kind="copy",
      include_phase=include_phase,
      required=0,
      include_in_prompt=1,
      failure_code=fc("stage_ramp_contract"),
      notes="Upstream stage_ramp_contract output (when produced before Phase 3).",
    ),
  ]


def all_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  for contract_name, include_phase in CONTRACTS:
    rows.extend(_common_rows(contract_name, include_phase))
  return rows


_INSERT_SQL = """
INSERT INTO post_intake_gpt_context_lookup
  (contract_name, context_key, context_group, source_kind, source_path,
   transform_kind, include_phase, required, include_in_prompt,
   max_items, max_chars, failure_code, context_status, notes)
VALUES
  (%(contract_name)s, %(context_key)s, %(context_group)s, %(source_kind)s,
   %(source_path)s, %(transform_kind)s, %(include_phase)s, %(required)s,
   %(include_in_prompt)s, %(max_items)s, %(max_chars)s, %(failure_code)s,
   %(context_status)s, %(notes)s)
ON DUPLICATE KEY UPDATE
  context_group = VALUES(context_group),
  source_kind = VALUES(source_kind),
  source_path = VALUES(source_path),
  transform_kind = VALUES(transform_kind),
  required = VALUES(required),
  include_in_prompt = VALUES(include_in_prompt),
  max_items = VALUES(max_items),
  max_chars = VALUES(max_chars),
  failure_code = VALUES(failure_code),
  context_status = VALUES(context_status),
  notes = VALUES(notes),
  updated_at = CURRENT_TIMESTAMP(6);
"""


def main() -> int:
  rows = all_rows()
  conn = get_mysql_connection()
  try:
    cur = conn.cursor()
    cur.executemany(_INSERT_SQL, rows)
    conn.commit()
    print(f"upserted {cur.rowcount} rows for {len(set(r['contract_name'] for r in rows))} contracts")
    cur.close()
  finally:
    conn.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
