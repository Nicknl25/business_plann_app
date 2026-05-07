"""Phase 3 — Consultant context resolver.

Thin adapter that wires the three Phase 3 GPT consultants
(band shaping, target shaping, conflict adjudication) to the existing
declarative context-feeding table ``post_intake_gpt_context_lookup``.

Pattern (matches the legacy contracts in post_intake_contracts/runner.py):

  1. Caller (orchestrator) supplies the runtime inputs that already
     exist in scope when the consultants run: business_facts, ops_json,
     target_market_json, people_json, financials_json,
     financials_year1_json, fulfillment_json, marketing_model_json,
     planning_mode, planning_mode_reason, business_profile_for_cohort,
     and the optional stage_ramp_contract from upstream.
  2. This resolver assembles a wide candidate payload keyed by the
     context_keys the table declares for the three new contracts (raw
     signals, not pre-classified labels — GPT does the classification).
  3. ``post_intake_gpt_context_filter_payload`` enforces the contract:
     it whitelists, applies max_items truncation, and raises if a
     ``required=1`` row's context_key is missing from the payload.

The resolver does NOT reimplement the lookup, the filter, or the
budget enforcement — those live in ``post_intake_mapping.py``. It is
strictly an assembler that hands a payload to the existing machinery.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _shallow_business_identity(
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Dict[str, Any]:
  fact_template = (business_facts or {}).get("fact_template")
  if not isinstance(fact_template, dict):
    fact_template = {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  return {
    "business_type": _clean_text(fact_template.get("business_type"))
    or _clean_text((business_facts or {}).get("business_type")),
    "business_naics_6": _clean_text(fact_template.get("business_naics_6"))
    or _clean_text(ops.get("business_naics_6"))
    or _clean_text((business_facts or {}).get("business_naics_6")),
    "business_naics_2": _clean_text(fact_template.get("business_naics_2"))
    or _clean_text(ops.get("business_naics_2")),
    "business_stage": _clean_text(fact_template.get("business_stage"))
    or _clean_text((business_facts or {}).get("business_stage")),
    "business_model": _clean_text(fact_template.get("business_model"))
    or _clean_text((business_facts or {}).get("business_model")),
    "primary_offering_summary": _clean_text(
      fact_template.get("primary_offering_summary")
    )[:480],
  }


def _business_descriptors(business_facts: Dict[str, Any]) -> Dict[str, Any]:
  fact_template = (business_facts or {}).get("fact_template")
  if not isinstance(fact_template, dict):
    fact_template = {}
  return {
    "growth_intent": _clean_text(fact_template.get("growth_intent"))[:480],
    "competitive_context": _clean_text(fact_template.get("competitive_context"))[:480],
    "operating_model_summary": _clean_text(
      fact_template.get("operating_model_summary")
    )[:480],
    "founder_intent_summary": _clean_text(
      fact_template.get("founder_intent_summary")
    )[:480],
  }


def _financial_snapshot(financials_json: Dict[str, Any]) -> Dict[str, Any]:
  fin = financials_json if isinstance(financials_json, dict) else {}
  keys = (
    "current_revenue",
    "current_cogs",
    "ar_balance",
    "ap_balance",
    "inventory_balance",
    "debt_balance",
    "cash_balance",
    "fixed_assets_balance",
    "equity_balance",
    "cogs_percent_of_revenue",
    "marketing_percent_of_revenue",
    "r_and_d_percent",
    "research_and_development_percent",
    "rd_percent_of_revenue",
    "taxes_percent",
  )
  return {key: fin.get(key) for key in keys if fin.get(key) is not None}


def _year1_projection(financials_year1_json: Dict[str, Any]) -> Dict[str, Any]:
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  keys = (
    "company_revenue_total_year1",
    "revenue_total_year1",
    "cogs_year_one",
    "gross_profit_year_one",
    "operating_expenses_year_one",
    "ebitda_year_one",
    "headcount_year_one",
  )
  return {key: year1.get(key) for key in keys if year1.get(key) is not None}


def _planning_mode_context(
  planning_mode: str,
  planning_mode_reason: str,
) -> Dict[str, Any]:
  return {
    "planning_mode": _clean_text(planning_mode),
    "planning_mode_reason": _clean_text(planning_mode_reason)[:480],
  }


def _shallow_dict(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(payload, dict):
    return {}
  return copy.deepcopy(payload)


def resolve_consultant_context(
  *,
  contract_name: str,
  include_phase: str,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  fulfillment_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  planning_mode_reason: Optional[str] = None,
  business_profile_for_cohort: Optional[Dict[str, Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Resolve the GPT context dict for a Phase 3 consultant.

  Assembles the wide candidate payload and runs it through the existing
  ``post_intake_gpt_context_lookup`` filter for the given contract +
  phase. Returned dict is keyed by the context_keys declared in the
  table (with rows where ``include_in_prompt=1``).

  Args:
    contract_name: row filter for ``post_intake_gpt_context_lookup``.
    include_phase: row filter (``band_shaping`` / ``target_shaping`` /
      ``conflict_adjudication`` for the three new contracts).
    draft_id, planning_run_id: process-tracing identifiers.
    business_facts ... marketing_model_json: the runtime inputs already
      in scope at the orchestrator's Phase 3 call site.
    business_profile_for_cohort: the small dict the orchestrator builds
      for the cohort band resolver (naics_6, target_annual_revenue,
      stage, business_model). Useful as a compact summary signal.
    stage_ramp_contract: the upstream stage-ramp contract output, when
      available. Conveys the pre-convergence quarter trajectory plan.
    extra_context: optional additional fields a particular caller wants
      to expose under context_keys declared in the table.

  Raises:
    RuntimeError: when the table has no rows for (contract_name, phase)
      or when a ``required=1`` context_key is missing from the assembled
      payload. Both are raised by the existing filter_payload helper.
  """
  candidate: Dict[str, Any] = {
    "draft_id": _clean_text(draft_id),
    "planning_run_id": _clean_text(planning_run_id),
    "business_identity": _shallow_business_identity(
      business_facts or {}, ops_json or {}
    ),
    "business_descriptors": _business_descriptors(business_facts or {}),
    "financial_snapshot": _financial_snapshot(financials_json or {}),
    "year1_projection": _year1_projection(financials_year1_json or {}),
    "planning_mode_context": _planning_mode_context(
      planning_mode or "", planning_mode_reason or ""
    ),
    "business_profile_for_cohort": _shallow_dict(business_profile_for_cohort),
    "target_market_signals": _shallow_dict(target_market_json),
    "people_capability_signals": _shallow_dict(people_json),
    "fulfillment_model_signals": _shallow_dict(fulfillment_json),
    "marketing_model_signals": _shallow_dict(marketing_model_json),
    "stage_ramp_contract": _shallow_dict(stage_ramp_contract),
  }
  if isinstance(extra_context, dict):
    for key, value in extra_context.items():
      candidate[_clean_text(key)] = copy.deepcopy(value)

  from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
    post_intake_gpt_context_filter_payload,
  )

  return post_intake_gpt_context_filter_payload(
    contract_name=_clean_text(contract_name),
    payload=candidate,
    include_phase=_clean_text(include_phase),
  )
