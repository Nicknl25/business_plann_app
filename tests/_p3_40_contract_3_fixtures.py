"""Shared fixture builders for Contract 3 (SolverInputContract)
acceptance tests. Same single-source-of-truth pattern as
``_p3_40_contract_1_fixtures.py`` and
``_p3_40_contract_2_fixtures.py``.

Module is leading-underscore-prefixed so the test runner does NOT
auto-discover it as a test module.

Re-uses Contract 1 + 2 fixtures so composed sub-contract fields
(``applied_model_input_json``, ``catalog_source_model_input_json``,
``applied_finmo_json``, ``stage_ramp_contract``,
``payroll_headcount``) stay in lockstep with the upstream
fixtures.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


# Re-use Contract 1 fixtures for the two model_input_json fields.
from _p3_40_contract_1_fixtures import (  # noqa: E402
  valid_top_level as valid_model_input_json_dict,
)
# Re-use Contract 2 fixtures for finmo_json, stage_ramp_contract,
# and payroll_headcount.
from _p3_40_contract_2_fixtures import (  # noqa: E402
  valid_finmo_output_dict,
  valid_payroll_headcount_dict,
  valid_stage_ramp_contract_dict,
)


# ---------------------------------------------------------------------------
# BusinessFactsForSolverContract
# ---------------------------------------------------------------------------

def valid_business_facts_dict() -> Dict[str, Any]:
  """Minimal-valid business_facts payload. ``fact_template`` is the
  only typed key (Flag 4 opaque for first cut); other top-level
  keys are permitted via extra=ignore but tests don't add any."""
  return {
    "fact_template": {
      "business_stage": "growth",
      "business_model": "saas",
    },
  }


# ---------------------------------------------------------------------------
# Top-level SolverInputContract
# ---------------------------------------------------------------------------

def valid_solver_input_dict(
  *,
  include_stage_ramp_contract: bool = True,
  include_payroll_headcount: bool = True,
  include_planning_context_summary_json: bool = True,
  include_grid_application_summary: bool = True,
) -> Dict[str, Any]:
  """Build a valid SolverInputContract dict.

  Defaults populate all 21 fields. The four ``include_*`` kwargs
  control the 4 optional fields so tests can exercise the
  Optional-absent paths.
  """
  model_input = valid_model_input_json_dict()
  payload: Dict[str, Any] = {
    "draft_id": "draft_test_001",
    "planning_run_id": "run_test_001",
    "business_facts": valid_business_facts_dict(),
    "ops_json": {"business_naics_6": "722515"},
    "financials_json": {},
    "financials_year1_json": {},
    "applied_model_input_json": model_input,
    "applied_finmo_json": valid_finmo_output_dict(),
    "planning_mode": "rebalance",
    "planning_mode_reason": "default for tests",
    "people_json": {},
    "fulfillment_json": {},
    "marketing_model_json": {},
    "target_market_json": {},
    "planning_result": {},
    # catalog_source_model_input_json shares Contract 1 shape per
    # Flag 6 (kept required per Flag 2 even though Tier-F unread).
    # Use the same fixture so the contract_versions_agree invariant
    # (4.5 / Flag 8(b)) is satisfied by default.
    "catalog_source_model_input_json": valid_model_input_json_dict(),
  }
  if include_planning_context_summary_json:
    payload["planning_context_summary_json"] = {}
  if include_grid_application_summary:
    payload["grid_application_summary"] = {}
  if include_stage_ramp_contract:
    payload["stage_ramp_contract"] = valid_stage_ramp_contract_dict()
  if include_payroll_headcount:
    payload["payroll_headcount"] = valid_payroll_headcount_dict()
  return payload
