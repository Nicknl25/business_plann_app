"""Shared fixture builders for Contract 4 (SolverOutputContract)
acceptance tests. Same single-source-of-truth pattern as
Contracts 1, 2, 3 fixture modules.

Module is leading-underscore-prefixed so the test runner does NOT
auto-discover it as a test module.

Re-uses Contract 1 + 2 fixtures so composed sub-contract fields
(``model_input_json``, ``finmo_json``, ``payroll_headcount``,
``debt_schedule``) stay in lockstep with the upstream fixtures.

Adds new fixture for ``capital_lease_schedule`` per Flag 5
override. Shape lifted verbatim from the writer at
``post_intake_capital_lease/schedule.py:222-261``.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from _p3_40_contract_1_fixtures import (  # noqa: E402
  valid_top_level as valid_model_input_json_dict,
)
from _p3_40_contract_2_fixtures import (  # noqa: E402
  valid_debt_schedule_dict,
  valid_finmo_output_dict,
  valid_payroll_headcount_dict,
)


# ---------------------------------------------------------------------------
# CapitalLeaseScheduleRow + CapitalLeaseScheduleContract (Flag 5 override)
# ---------------------------------------------------------------------------

def valid_capital_lease_schedule_row(quarter_index: int = 1) -> Dict[str, Any]:
  """One row in ``capital_lease_schedule.rows``. 11 fields lifted
  verbatim from the writer at schedule.py:222-251."""
  opening = 100000.0
  principal = 5000.0
  interest = 2000.0
  closing = 95000.0
  rou_opening = 80000.0
  rou_closing = 76000.0
  asset_dep = 4000.0
  rate = 0.05
  return {
    "quarter_index": quarter_index,
    "date": "2026-01-01",
    "opening_balance": opening,
    "principal_payment": principal,
    "interest_payment": interest,
    "closing_balance": closing,
    "rou_asset_opening": rou_opening,
    "rou_asset_closing": rou_closing,
    "lease_asset_depreciation": asset_dep,
    "interest_rate": rate,
    "finmo_formula": (
      "closing = max(0, opening - principal); "
      "interest = opening * interest_rate; "
      "asset_depreciation = opening_balance_seed / depreciation_quarters"
    ),
  }


def valid_capital_lease_schedule_dict() -> Dict[str, Any]:
  """Envelope shape lifted verbatim from
  build_capital_lease_schedule_snapshot at schedule.py:251-261."""
  return {
    "contract_version": "post_intake_capital_lease_schedule_v1",
    "schedule_role": "persisted_final_capital_lease_schedule",
    "source_stage": "post_intake_finalize_validation",
    "horizon_quarters": 20,
    "depreciation_quarters": 20,
    "opening_balance_seed": 100000.0,
    "interest_rate": 0.05,
    "per_quarter_depreciation": 5000.0,
    "schedule_method": "declining_balance_straight_line_depreciation",
    "rows": [valid_capital_lease_schedule_row(q) for q in range(1, 21)],
  }


# ---------------------------------------------------------------------------
# Top-level SolverOutputContract
# ---------------------------------------------------------------------------

def valid_solver_output_dict(
  *,
  include_payroll_headcount: bool = True,
  include_debt_schedule: bool = True,
  include_capital_lease_schedule: bool = True,
  include_phantom_reads: bool = False,
  cascade_fired: bool = False,
) -> Dict[str, Any]:
  """Build a valid SolverOutputContract dict.

  Defaults match the orchestrator's most-common stamp profile:
  cascade did NOT fire, no phantom-read fields populated. The
  kwargs toggle the 4 optional sub-contract fields + the 5
  phantom-read fields + the cascade-fired path (which flips both
  plan_confidence and adaptation_cascade_diagnostics together
  to satisfy invariant 4.3).
  """
  payload: Dict[str, Any] = {
    "model_input_json": valid_model_input_json_dict(),
    "finmo_json": valid_finmo_output_dict(),
    # Cross-field invariant 4.3 ties these two together:
    "plan_confidence": (
      "medium_gpt_band_relaxation" if cascade_fired else "high_no_adaptation"
    ),
    "target_seeking_diagnostics": {"iter_count": 5},
    "adaptive_policy": {"stage_family": "growth"},
  }
  if cascade_fired:
    payload["adaptation_cascade_diagnostics"] = {"tier_landed": 3}
  if include_payroll_headcount:
    payload["payroll_headcount"] = valid_payroll_headcount_dict()
  if include_debt_schedule:
    payload["debt_schedule"] = valid_debt_schedule_dict()
  if include_capital_lease_schedule:
    payload["capital_lease_schedule"] = valid_capital_lease_schedule_dict()
  if include_phantom_reads:
    payload["planning_run_json"] = {}
    payload["numeric_solver_feedback_json"] = {}
    payload["planning_runtime_json"] = {}
    payload["planning_context_summary_json"] = {}
    payload["draft_id"] = "draft_test_001"
  return payload
