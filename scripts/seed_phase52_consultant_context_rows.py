"""Phase 7 — Seed per-scope rows for the three consultant contracts.

Replaces the Phase 5.2 rows. Per the Phase 7 audit
(``docs/phase_7_context_table_curation_audit.md``), the rows feed each
consultant call raw signals from the populated intake JSON (operating_model,
financials, target_market, financials_year1, marketing_model scalars,
people_summary) instead of pre-classified `business_facts.fact_template.*`
labels.

Removed (pre-classified labels):
  - business_facts.fact_template.business_type
  - business_facts.fact_template.business_stage
  - business_facts.fact_template.business_model
  Replaced by `operating_model` (slim) + `business_start_date` (raw signal).

New per-scope inputs:
  - operating_model: slim_operating_model transform on operating_model_json,
    fed across all three consultant calls; carries business_type / NAICS /
    consumer_type / sales_modality / shipping_method / capacity_driver /
    unit_* / lob_models / milestones — the discriminating raw signals.
  - business_start_date: intake_field; lets GPT compute business age.
  - target_market_summary: target_market_json:marketing_plan_summary.
  - target_market_consumer_type: target_market_json:consumer_type.
  - marketing_model scalars: marketing_intensity, baseline_marketing_percent,
    expected_customers_or_clients_year1, expected_units_year1,
    capture_rate_year1, reachable_market_b2b, reachable_market_b2c (drops
    the 6.5KB signature + 4.2KB narrative).
  - people_summary: people_json:inferred_roles_summary.
  - address_state: intake_field for geographic rent / G&A signal.
  - financials_full_snapshot: financials_json (capped at 1500c) for
    target_shaping + conflict_adjudication consultants.
  - financials_year1_advisory: financials_year1_json (capped) for
    target_shaping + conflict_adjudication. Per directive: advisory only,
    not authoritative.

Out of scope per directive (deferred):
  - Per-lever scope filter for `financials_year1_advisory` on band_shaping:
    the audit recommended limiting it to revenue levers (Capacity / Unit
    Price / Utilization), but the lookup table has no scope_filter column
    and the resolver supports placeholder-driven filtering only. Phase 7
    feeds it to target_shaping + conflict_adjudication universally and
    excludes it from band_shaping entirely. A future phase can add a
    scope_filter column when scope-level inclusion becomes load-bearing.

Idempotent: deletes any existing rows for the three contract names then
inserts the new per-scope rows.

Run from repo root:
  python scripts/seed_phase52_consultant_context_rows.py
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


CONTRACT_NAMES = (
  "post_intake_band_shaping_consultant",
  "post_intake_target_shaping_consultant",
  "post_intake_conflict_adjudication_consultant",
)


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


# Marketing scalar fields fed individually as separate rows. Drops signature
# (6.5KB hash) and marketing_basis_summary (4.2KB narrative) which carry no
# discriminating signal for band shaping.
_MARKETING_SCALAR_FIELDS = (
  "marketing_intensity",
  "baseline_marketing_percent",
  "expected_customers_or_clients_year1",
  "expected_units_year1",
  "capture_rate_year1",
  "reachable_market_b2b",
  "reachable_market_b2c",
)


def _universal_rows(*, contract: str, phase: str, fc) -> List[Dict[str, Any]]:
  """Rows that flow on every consultant call regardless of scope_key.

  These are the always-on raw signals. Replaces the removed
  `business_facts.fact_template.*` pre-classified labels with raw fields:
  business_start_date (raw date — GPT infers age) and the slim
  operating_model bundle (consumer_type / sales_modality / shipping_method
  / capacity_driver / lob_models / etc.).
  """
  return [
    _row(
      contract_name=contract, context_key="__openai_request_budget__",
      context_group="budget", source_kind="data_query",
      source_path="industry_baseline_for_naics:metric_key=ebitda_margin,naics_6=000000",
      transform_kind="request_char_budget",
      include_phase=phase, required=0, include_in_prompt=0,
      max_chars=7500,
      failure_code=f"{contract}_payload_budget_exceeded",
      notes="Per-call payload cap. Phase 7 raised from 5000 to 7500 to "
            "accommodate operating_model slim (1500c) + advisory financials.",
    ),
    _row(
      contract_name=contract, context_key="business_naics_6",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_profile_for_cohort.naics_6",
      transform_kind="copy",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=20,
      failure_code=fc("business_naics_6"),
    ),
    _row(
      contract_name=contract, context_key="business_start_date",
      context_group="business_world", source_kind="intake_field",
      source_path="business_start_date",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=40,
      failure_code=fc("business_start_date"),
      notes="Raw date — replaces pre-classified business_stage label. "
            "GPT computes age (start vs today).",
    ),
    _row(
      contract_name=contract, context_key="business_profile_for_cohort",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_profile_for_cohort",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=500,
      failure_code=fc("business_profile_for_cohort"),
    ),
    _row(
      contract_name=contract, context_key="planning_mode_context",
      context_group="policy", source_kind="runtime_object",
      source_path="planning_mode_context",
      transform_kind="copy",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=800,
      failure_code=fc("planning_mode_context"),
    ),
    _row(
      contract_name=contract, context_key="operating_model",
      context_group="business_world", source_kind="intake_json_field",
      source_path="operating_model_json:",
      transform_kind="slim_operating_model",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=1600,
      failure_code=fc("operating_model"),
      notes="Slim curated subset — consumer_type, sales_modality, "
            "shipping_method, capacity_driver, unit_*, lob_models, "
            "milestones. Drops business_description_summary and "
            "competitive_advantage narratives.",
    ),
    _row(
      contract_name=contract, context_key="address_state",
      context_group="business_world", source_kind="intake_field",
      source_path="address_state",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=10,
      failure_code=fc("address_state"),
      notes="Geographic signal — rent / G&A / labor cost calibration.",
    ),
  ]


# ----- Band shaping (per-lever) ------------------------------------------------


def _band_shaping_rows() -> List[Dict[str, Any]]:
  contract = "post_intake_band_shaping_consultant"
  phase = "band_shaping"
  fc = lambda key: f"{contract}_{key}_invalid"
  rows = _universal_rows(contract=contract, phase=phase, fc=fc)
  rows.extend([
    _row(
      contract_name=contract, context_key="target_market_summary",
      context_group="business_world", source_kind="intake_json_field",
      source_path="target_market_json:marketing_plan_summary",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=3000,
      failure_code=fc("target_market_summary"),
      notes="ICP narrative — relevant to revenue + marketing band shaping.",
    ),
    _row(
      contract_name=contract, context_key="target_market_consumer_type",
      context_group="business_world", source_kind="intake_json_field",
      source_path="target_market_json:consumer_type",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=40,
      failure_code=fc("target_market_consumer_type"),
      notes="b2b / b2c / mixed — drives AR Days, payment terms band.",
    ),
    _row(
      contract_name=contract, context_key="people_summary",
      context_group="business_world", source_kind="intake_json_field",
      source_path="people_json:inferred_roles_summary",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=1500,
      failure_code=fc("people_summary"),
      notes="Year-1 roles narrative — R&D / G&A / payroll signal.",
    ),
    _row(
      contract_name=contract, context_key="financials_snapshot",
      context_group="business_world", source_kind="intake_json_field",
      source_path="financials_json:",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=3500,
      failure_code=fc("financials_snapshot"),
      notes="Current-state P&L + balance-sheet scalars — anchors GPT to "
            "operator's existing ratios for band-shaping calibration.",
    ),
  ])
  # Marketing scalar signals — separate rows skip the 6.5KB signature blob.
  for field in _MARKETING_SCALAR_FIELDS:
    rows.append(_row(
      contract_name=contract, context_key=f"marketing_{field}",
      context_group="business_world", source_kind="intake_json_field",
      source_path=f"marketing_model_json:{field}",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=200,
      failure_code=fc(f"marketing_{field}"),
    ))
  # Per-lever rows (scope_key.lever_id required) -----
  rows.extend([
    _row(
      contract_name=contract, context_key="python_proposed_band",
      context_group="model_input", source_kind="runtime_object",
      source_path="envelope_proposal.drivers.{lever_id}",
      transform_kind="slim_lever_entry",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=2500,
      failure_code=fc("python_proposed_band"),
      notes="The Python-proposer's band for the lever in scope (post-cohort, "
            "pre-GPT). Includes provenance.calibration_source and "
            "applicability.reason — both critical for the buffer-rule check.",
    ),
    _row(
      contract_name=contract, context_key="lever_mapping_metadata",
      context_group="model_input", source_kind="data_query",
      source_path="mapping_row_for_lever:lever_id={lever_id}",
      transform_kind="slim_mapping_row",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=1500,
      failure_code=fc("lever_mapping_metadata"),
      notes="Mapping table row for the lever — value_kind, control_owner, "
            "absolute_min/max bounds, applicability_default.",
    ),
  ])
  return rows


# ----- Target shaping (per-metric) --------------------------------------------


def _target_shaping_rows() -> List[Dict[str, Any]]:
  contract = "post_intake_target_shaping_consultant"
  phase = "target_shaping"
  fc = lambda key: f"{contract}_{key}_invalid"
  rows = _universal_rows(contract=contract, phase=phase, fc=fc)
  rows.extend([
    _row(
      contract_name=contract, context_key="target_market_summary",
      context_group="business_world", source_kind="intake_json_field",
      source_path="target_market_json:marketing_plan_summary",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=3000,
      failure_code=fc("target_market_summary"),
    ),
    _row(
      contract_name=contract, context_key="people_summary",
      context_group="business_world", source_kind="intake_json_field",
      source_path="people_json:inferred_roles_summary",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=1500,
      failure_code=fc("people_summary"),
    ),
    _row(
      contract_name=contract, context_key="financials_snapshot",
      context_group="business_world", source_kind="intake_json_field",
      source_path="financials_json:",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=3500,
      failure_code=fc("financials_snapshot"),
    ),
    _row(
      contract_name=contract, context_key="financials_year1_advisory",
      context_group="business_world", source_kind="intake_json_field",
      source_path="financials_year1_json:",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=4500,
      failure_code=fc("financials_year1_advisory"),
      notes="Operator's projected Year-1 revenue + LOB structure. "
            "ADVISORY ONLY per directive — context for target-shaping "
            "conversation, not authoritative override.",
    ),
    # Per-metric rows
    _row(
      contract_name=contract, context_key="python_proposed_target",
      context_group="model_input", source_kind="runtime_object",
      source_path="targets_proposal.metrics.{metric_key}",
      transform_kind="slim_metric_entry",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=2500,
      failure_code=fc("python_proposed_target"),
    ),
    _row(
      contract_name=contract, context_key="realism_check_metadata",
      context_group="model_input", source_kind="data_query",
      source_path="realism_row_for_metric:metric_key={metric_key}",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=1500,
      failure_code=fc("realism_check_metadata"),
    ),
  ])
  return rows


# ----- Conflict adjudication (per-conflict) -----------------------------------


def _conflict_adjudication_rows() -> List[Dict[str, Any]]:
  contract = "post_intake_conflict_adjudication_consultant"
  phase = "conflict_adjudication"
  fc = lambda key: f"{contract}_{key}_invalid"
  rows = _universal_rows(contract=contract, phase=phase, fc=fc)
  rows.extend([
    _row(
      contract_name=contract, context_key="target_market_summary",
      context_group="business_world", source_kind="intake_json_field",
      source_path="target_market_json:marketing_plan_summary",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=3000,
      failure_code=fc("target_market_summary"),
    ),
    _row(
      contract_name=contract, context_key="financials_full_snapshot",
      context_group="business_world", source_kind="intake_json_field",
      source_path="financials_json:",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=3500,
      failure_code=fc("financials_full_snapshot"),
      notes="Operator's full current-state P&L + balance-sheet — needed "
            "for cross-metric conflict reasoning.",
    ),
    _row(
      contract_name=contract, context_key="financials_year1_advisory",
      context_group="business_world", source_kind="intake_json_field",
      source_path="financials_year1_json:",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=4500,
      failure_code=fc("financials_year1_advisory"),
      notes="The strongest case for financials_year1_json per directive — "
            "what the operator said they'd do for conflict resolution.",
    ),
    _row(
      contract_name=contract, context_key="lever_mapping_metadata",
      context_group="model_input", source_kind="data_query",
      source_path="mapping_row_for_lever:lever_id={lever_id}",
      transform_kind="slim_mapping_row",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=1500,
      failure_code=fc("lever_mapping_metadata"),
    ),
    _row(
      contract_name=contract, context_key="lever_python_proposed_band",
      context_group="model_input", source_kind="runtime_object",
      source_path="envelope_proposal.drivers.{lever_id}",
      transform_kind="slim_lever_entry",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=2500,
      failure_code=fc("lever_python_proposed_band"),
    ),
  ])
  return rows


def all_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  rows.extend(_band_shaping_rows())
  rows.extend(_target_shaping_rows())
  rows.extend(_conflict_adjudication_rows())
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
"""

_PLACEHOLDERS = ", ".join(["%s"] * len(CONTRACT_NAMES))
_DELETE_SQL = (
  f"DELETE FROM post_intake_gpt_context_lookup WHERE contract_name IN ({_PLACEHOLDERS})"
)


def main() -> int:
  rows = all_rows()
  conn = get_mysql_connection()
  try:
    cur = conn.cursor()
    cur.execute(_DELETE_SQL, CONTRACT_NAMES)
    deleted = cur.rowcount
    cur.executemany(_INSERT_SQL, rows)
    conn.commit()
    print(f"deleted {deleted} stale rows for {len(CONTRACT_NAMES)} contracts")
    print(f"inserted {cur.rowcount} Phase 7 curated per-scope rows")
    cur.close()
  finally:
    conn.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
