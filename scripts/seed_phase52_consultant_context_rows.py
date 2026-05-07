"""Phase 5.2 — Seed per-scope rows for the three consultant contracts.

Replaces the Phase 5.1 rows (single-call per business) with per-scope
rows declaring exactly what each consultant call sees:

  - post_intake_band_shaping_consultant @ band_shaping
      * global rows: business_identity, naics_descriptors, planning_mode_context
      * per-lever rows (scope_key.lever_id): python_proposed_band,
        intake_implied_value, mapping_row_metadata
  - post_intake_target_shaping_consultant @ target_shaping
      * global rows: business_identity, planning_mode_context, stage_ramp_summary
      * per-metric rows (scope_key.metric_key): python_proposed_target,
        realism_row_metadata, industry_baseline_for_metric
  - post_intake_conflict_adjudication_consultant @ conflict_adjudication
      * global rows: business_identity, planning_mode_context
      * per-lever rows: python_proposed_band, mapping_row_metadata,
        intake_implied_value (the conflict value)

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


# ----- Band shaping (per-lever) ------------------------------------------------


def _band_shaping_rows() -> List[Dict[str, Any]]:
  contract = "post_intake_band_shaping_consultant"
  phase = "band_shaping"
  fc = lambda key: f"{contract}_{key}_invalid"
  return [
    _row(
      contract_name=contract, context_key="__openai_request_budget__",
      context_group="budget", source_kind="data_query",
      source_path="industry_baseline_for_naics:metric_key=ebitda_margin,naics_6=000000",
      transform_kind="request_char_budget",
      include_phase=phase, required=0, include_in_prompt=0,
      max_chars=5000,
      failure_code=f"{contract}_payload_budget_exceeded",
      notes="Per-call payload cap (Phase 5.2 R1: median <3KB, max <5KB).",
    ),
    # ----- Global rows (no scope_key required) -----
    _row(
      contract_name=contract, context_key="business_type",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_facts.fact_template.business_type",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=200,
      failure_code=fc("business_type"),
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
      contract_name=contract, context_key="business_stage",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_facts.fact_template.business_stage",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=80,
      failure_code=fc("business_stage"),
    ),
    _row(
      contract_name=contract, context_key="business_model",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_facts.fact_template.business_model",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=80,
      failure_code=fc("business_model"),
    ),
    _row(
      contract_name=contract, context_key="planning_mode_context",
      context_group="policy", source_kind="runtime_object",
      source_path="planning_mode_context",
      transform_kind="copy",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=600,
      failure_code=fc("planning_mode_context"),
    ),
    _row(
      contract_name=contract, context_key="business_profile_for_cohort",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_profile_for_cohort",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=400,
      failure_code=fc("business_profile_for_cohort"),
    ),
    # ----- Per-lever rows (scope_key.lever_id required) -----
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
  ]


# ----- Target shaping (per-metric) --------------------------------------------


def _target_shaping_rows() -> List[Dict[str, Any]]:
  contract = "post_intake_target_shaping_consultant"
  phase = "target_shaping"
  fc = lambda key: f"{contract}_{key}_invalid"
  return [
    _row(
      contract_name=contract, context_key="__openai_request_budget__",
      context_group="budget", source_kind="data_query",
      source_path="industry_baseline_for_naics:metric_key=ebitda_margin,naics_6=000000",
      transform_kind="request_char_budget",
      include_phase=phase, required=0, include_in_prompt=0,
      max_chars=5000,
      failure_code=f"{contract}_payload_budget_exceeded",
    ),
    _row(
      contract_name=contract, context_key="business_type",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_facts.fact_template.business_type",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=200,
      failure_code=fc("business_type"),
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
      contract_name=contract, context_key="business_stage",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_facts.fact_template.business_stage",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=80,
      failure_code=fc("business_stage"),
    ),
    _row(
      contract_name=contract, context_key="planning_mode_context",
      context_group="policy", source_kind="runtime_object",
      source_path="planning_mode_context",
      transform_kind="copy",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=600,
      failure_code=fc("planning_mode_context"),
    ),
    _row(
      contract_name=contract, context_key="business_profile_for_cohort",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_profile_for_cohort",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=400,
      failure_code=fc("business_profile_for_cohort"),
    ),
    # ----- Per-metric rows -----
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
  ]


# ----- Conflict adjudication (per-conflict) -----------------------------------


def _conflict_adjudication_rows() -> List[Dict[str, Any]]:
  contract = "post_intake_conflict_adjudication_consultant"
  phase = "conflict_adjudication"
  fc = lambda key: f"{contract}_{key}_invalid"
  return [
    _row(
      contract_name=contract, context_key="__openai_request_budget__",
      context_group="budget", source_kind="data_query",
      source_path="industry_baseline_for_naics:metric_key=ebitda_margin,naics_6=000000",
      transform_kind="request_char_budget",
      include_phase=phase, required=0, include_in_prompt=0,
      max_chars=5000,
      failure_code=f"{contract}_payload_budget_exceeded",
    ),
    _row(
      contract_name=contract, context_key="business_type",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_facts.fact_template.business_type",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=200,
      failure_code=fc("business_type"),
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
      contract_name=contract, context_key="business_stage",
      context_group="business_world", source_kind="runtime_object",
      source_path="business_facts.fact_template.business_stage",
      transform_kind="copy",
      include_phase=phase, required=0, include_in_prompt=1,
      max_chars=80,
      failure_code=fc("business_stage"),
    ),
    _row(
      contract_name=contract, context_key="planning_mode_context",
      context_group="policy", source_kind="runtime_object",
      source_path="planning_mode_context",
      transform_kind="copy",
      include_phase=phase, required=1, include_in_prompt=1,
      max_chars=600,
      failure_code=fc("planning_mode_context"),
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
  ]


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
    print(f"deleted {deleted} stale Phase 5.1 rows")
    print(f"inserted {cur.rowcount} Phase 5.2 per-scope rows for {len(CONTRACT_NAMES)} contracts")
    cur.close()
  finally:
    conn.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
