"""Shared fixture builders for Contract 7
(AmalgamatedSessionContract) acceptance tests.

Module is leading-underscore-prefixed so the test runner does NOT
auto-discover it as a test module.

Re-uses Contract 6 fixtures for mirror.bands (composes
GetBandsViewContract per F1). Otherwise standalone --
Contract 7 has ZERO composition with Contracts 1-5 / 3-4.

Fixtures provide minimal-valid + invariant-friendly defaults
(F5 alias-sync + F6 outside_band filter satisfied).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from _p3_40_contract_6_fixtures import (  # noqa: E402
  valid_get_bands_view_dict,
)


# ---------------------------------------------------------------------------
# Shape B -- valid_recent_decision_dict REMOVED per Cleanup 3/6
# (Contract 7 R10 closure). RecentDecisionContract + Mirror.
# recent_decisions / record_decision() all dropped upstream.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Shape E -- LeverMarginEntryContract
# ---------------------------------------------------------------------------

def valid_lever_margin_entry_dict(
  *,
  lever_id: str = "gross_margin_percent_lever",
  section: str = "drivers",
  outside_band: bool = True,
) -> Dict[str, Any]:
  """8-field lever margin entry per mirror.py:135-145. F6 (iv)
  default: outside_band=True (matches Bug 3 producer filter)."""
  return {
    "lever_id": lever_id,
    "section": section,
    "current": 0.30,
    "band_min": 0.40,
    "band_max": 0.55,
    "outside_band": outside_band,
    "pinned_min": False,
    "pinned_max": False,
  }


# ---------------------------------------------------------------------------
# Shape D -- ValidationStateProjectionContract
# ---------------------------------------------------------------------------

def valid_validation_state_projection_dict(
  *,
  all_pass: bool = False,
  failing_check_count: int = 2,
  failing_check_names: Optional[List[str]] = None,
  failing_check_names_truncated: bool = False,
  failing_lever_margins_count: int = 1,
  failing_lever_margins_truncated: bool = False,
  strictness: str = "mini_finmo",
  round_number: int = 3,
) -> Dict[str, Any]:
  """11-field Bug 3 bounded projection per mirror.py:146-157.
  Defaults satisfy F6 (i)-(iv) invariants."""
  if failing_check_names is None:
    failing_check_names = ["check_revenue_growth_realism", "check_payroll_coverage"]
  return {
    "all_pass": all_pass,
    "round_number": round_number,
    "strictness": strictness,
    "failing_check_count": failing_check_count,
    "worst_failing_check": (
      failing_check_names[0] if failing_check_names else None
    ),
    "worst_failing_distance": 0.15,
    "failing_check_names": failing_check_names,
    "failing_check_names_truncated": failing_check_names_truncated,
    "failing_lever_margins": [
      valid_lever_margin_entry_dict() for _ in range(failing_lever_margins_count)
    ],
    "failing_lever_margins_truncated": failing_lever_margins_truncated,
    "evaluated_at": "2026-05-26T12:00:00+00:00",
  }


# ---------------------------------------------------------------------------
# plan_state -- 5 SECTIONS with opaque per-section payloads (F2 DEFER)
# ---------------------------------------------------------------------------

def valid_plan_state_dict(
  *,
  alias_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """plan_state with 5 SECTIONS populated. The 3-way alias
  triplet (balance_sheet / capex_rd_balance_seed / capex_rd) is
  satisfied by populating only balance_sheet + capex_rd both
  with the SAME payload per F5 alias-sync invariant.

  capex_rd_balance_seed is NOT in the 5-SECTIONS Literal so it
  cannot appear in plan_state under modern code paths (would
  fail field-level Literal validation). The alias-sync
  invariant fires for the 2 Literal-permitted keys
  (balance_sheet + capex_rd).
  """
  if alias_payload is None:
    alias_payload = {"placeholder": "bs_payload"}
  return {
    "stage_ramp": {"placeholder": "sr_payload"},
    "drivers": {"placeholder": "dr_payload"},
    "payroll": {"placeholder": "pr_payload"},
    "balance_sheet": alias_payload,
    "capex_rd": alias_payload,  # F5 alias-sync: SAME payload as balance_sheet
  }


# ---------------------------------------------------------------------------
# Shape A -- MirrorContract
# ---------------------------------------------------------------------------

def valid_mirror_dict(
  *,
  include_validation_state: bool = True,
  alias_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """6-field Mirror per mirror.py:73-82 post-Cleanup-3/6. Was
  9 fields pre-cleanup; R10 + R11 dropped recent_decisions +
  sequence_position + budget. Defaults match the build_mirror
  initial state -- validation_state populated."""
  payload: Dict[str, Any] = {
    "invariants": {
      "realism": "Operate within cohort-shape bounds.",
      "viability": "Every plan must pass.",
      "adaptation": "When inputs do not compose, restructure Q1 onward.",
    },
    "authority": "You may revise any value Q1 onward.",
    "business_facts": {
      "business_naics_6": "722515", "business_stage": "growth",
    },
    "plan_state": valid_plan_state_dict(alias_payload=alias_payload),
    "bands": {
      section: valid_get_bands_view_dict(section=section)
      for section in (
        "stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet",
      )
    },
  }
  if include_validation_state:
    payload["validation_state"] = valid_validation_state_projection_dict()
  return payload


# ---------------------------------------------------------------------------
# Top-level AmalgamatedSessionContract
# ---------------------------------------------------------------------------

def valid_amalgamated_session_dict(**mirror_kwargs) -> Dict[str, Any]:
  """Top-level wrapper -- thin per F0 design (single mirror
  field)."""
  return {"mirror": valid_mirror_dict(**mirror_kwargs)}
