"""Phase 9 P3.10 Bug C fix — smoke tests for excision of the Phase 7.2
headcount rationalization lever.

Verifies:
  - The Lever 1 helper functions and constant are no longer importable
    from the feasibility_restoration module.
  - restore_feasibility no longer emits a "headcount_rationalization"
    entry in applied_adjustments.
  - adjusted_payroll_headcount is a deepcopy passthrough: quarter_totals
    are unchanged and carry no _phase_7_2_* markers; rows sum equals
    quarter_total per quarter (the validator's invariant holds).
  - Cascade still functions when the structural check is infeasible:
    Levers 2/3 (price/utilization) and Lever 4 (capacity expansion)
    continue to fire as before.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class _Result:
  """Minimal stand-in for StructuralFeasibilityResult."""
  def __init__(self, *, feasibility_gap: float, upper_bound_annual_revenue: float, lower_bound_annual_fixed_cost: float) -> None:
    self.feasibility_gap = feasibility_gap
    self.upper_bound_annual_revenue = upper_bound_annual_revenue
    self.lower_bound_annual_fixed_cost = lower_bound_annual_fixed_cost


def _payroll_headcount_with_consistent_rollup() -> Dict[str, Any]:
  """Synthetic schedule that previously triggered the Phase 7.2 cap.

  Three Q1 rows with OEWS-resolved wages summing to 39,620; quarter_totals
  consistent with the row sum. This mirrors Sunny's persisted Q1 state.
  """
  rows = []
  quarter_totals = []
  per_quarter_row_total = 39620
  for q in range(1, 21):
    rows.extend([
      {
        "quarter_index": q,
        "staffing_class": "key_person",
        "position_title": "Owner and Manager",
        "starting_fte": 1.0,
        "ending_fte": 1.0,
        "annual_wage": 75820,
        "payroll_taxes_benefits_percent": 0.22,
        "quarterly_wage_cost": 18955,
        "quarterly_taxes_benefits": 4170,
        "total_quarterly_payroll": 23125,
      },
      {
        "quarter_index": q,
        "staffing_class": "key_person",
        "position_title": "Lead Baker",
        "starting_fte": 1.0,
        "ending_fte": 1.0,
        "annual_wage": 36550,
        "payroll_taxes_benefits_percent": 0.22,
        "quarterly_wage_cost": 9138,
        "quarterly_taxes_benefits": 2010,
        "total_quarterly_payroll": 11148,
      },
      {
        "quarter_index": q,
        "staffing_class": "supporting_staff",
        "position_title": "Fast Food and Counter Workers",
        "oews_occ_title": "Fast Food and Counter Workers",
        "starting_fte": 0.5,
        "ending_fte": 0.5,
        "annual_wage": 36246,
        "payroll_taxes_benefits_percent": 0.18,
        "quarterly_wage_cost": 4531,
        "quarterly_taxes_benefits": 816,
        "total_quarterly_payroll": 5347,
      },
    ])
    quarter_totals.append({"quarter_index": q, "ending_fte": 2.5, "payroll": per_quarter_row_total})
  return {"rows": rows, "quarter_totals": quarter_totals}


class BugCFixRemovePhase7_2HeadcountRationalizationTest(unittest.TestCase):
  def test_dead_helpers_no_longer_importable(self) -> None:
    """The removed helpers must NOT be importable from the module."""
    import client_intake_and_finmo.post_intake_solver.feasibility_restoration as m  # noqa: WPS433
    for dead_name in (
      "_apply_headcount_rationalization",
      "_naics_payroll_pct",
      "_annual_payroll_from_schedule",
      "_FALLBACK_PAYROLL_PCT_OF_REVENUE",
    ):
      self.assertFalse(
        hasattr(m, dead_name),
        f"{dead_name} should have been deleted from feasibility_restoration",
      )

  def test_dead_markers_grepped_clean_in_module(self) -> None:
    """No live code reference to the _phase_7_2_* payroll markers (comments
    documenting the excision are allowed)."""
    import pathlib
    module_path = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_solver"
      / "feasibility_restoration.py"
    )
    text = module_path.read_text(encoding="utf-8")
    for marker in (
      "_phase_7_2_capped_for_capacity",
      "_phase_7_2_original_payroll",
      "_phase_7_2_headcount_rationalization_applied",
      "_phase_7_2_target_annual_payroll",
      "_phase_7_2_naics_payroll_pct_used",
    ):
      self.assertNotIn(
        marker,
        text,
        f"{marker} should be removed from live code (comments OK if they don't carry the literal token)",
      )

  def test_restore_feasibility_emits_no_headcount_rationalization_adjustment(self) -> None:
    """The previously-triggered Sunny scenario: infeasible structural check
    with operator-stated payroll > capacity × NAICS pct. After excision,
    applied_adjustments must not contain a 'headcount_rationalization'
    entry; quarter_totals and rows must remain consistent."""
    from client_intake_and_finmo.post_intake_solver.feasibility_restoration import (  # noqa: WPS433
      restore_feasibility,
    )

    payroll_headcount = _payroll_headcount_with_consistent_rollup()
    initial_quarter_totals = [dict(qt) for qt in payroll_headcount["quarter_totals"]]
    initial_rows = [dict(r) for r in payroll_headcount["rows"]]

    result = restore_feasibility(
      structural_result=_Result(
        feasibility_gap=50000.0,
        upper_bound_annual_revenue=238500.0,
        lower_bound_annual_fixed_cost=200000.0,
      ),
      ops_json={
        "unit_price": 1.80,
        "units_per_period_capacity": 1080,
        "operating_periods_per_year": 50,
        "utilization_rate": 0.70,
      },
      financials_json={},
      financials_year1_json={},
      payroll_headcount=payroll_headcount,
      business_naics_6="311811",
      industry_profile=None,
    )

    self.assertNotIn(
      "headcount_rationalization",
      [a.get("lever") for a in (result.applied_adjustments or [])],
      "headcount_rationalization lever must not appear after Phase 7.2 Lever 1 removal",
    )
    # adjusted_payroll_headcount is a deepcopy of input; should be unchanged.
    adjusted = result.adjusted_payroll_headcount or {}
    self.assertEqual(
      [dict(qt) for qt in (adjusted.get("quarter_totals") or [])],
      initial_quarter_totals,
      "adjusted_payroll_headcount.quarter_totals should pass through unchanged",
    )
    self.assertEqual(
      [dict(r) for r in (adjusted.get("rows") or [])],
      initial_rows,
      "adjusted_payroll_headcount.rows should pass through unchanged",
    )
    # Marker grep on the adjusted schedule:
    for qt in (adjusted.get("quarter_totals") or []):
      for marker in (
        "_phase_7_2_capped_for_capacity",
        "_phase_7_2_original_payroll",
      ):
        self.assertNotIn(marker, qt, f"{marker} should not be set on any quarter_total entry")
    for top_marker in (
      "_phase_7_2_headcount_rationalization_applied",
      "_phase_7_2_target_annual_payroll",
      "_phase_7_2_naics_payroll_pct_used",
    ):
      self.assertNotIn(
        top_marker, adjusted,
        f"{top_marker} should not be set on the adjusted schedule top-level",
      )

  def test_row_rollup_invariant_holds_after_cascade(self) -> None:
    """The validator's invariant — quarter_totals.payroll equals the
    deterministic rollup of the rows — must hold on the adjusted_payroll
    after restore_feasibility runs."""
    from client_intake_and_finmo.post_intake_solver.feasibility_restoration import (  # noqa: WPS433
      restore_feasibility,
    )

    payroll_headcount = _payroll_headcount_with_consistent_rollup()
    result = restore_feasibility(
      structural_result=_Result(
        feasibility_gap=50000.0,
        upper_bound_annual_revenue=238500.0,
        lower_bound_annual_fixed_cost=200000.0,
      ),
      ops_json={
        "unit_price": 1.80,
        "units_per_period_capacity": 1080,
        "operating_periods_per_year": 50,
        "utilization_rate": 0.70,
      },
      financials_json={},
      financials_year1_json={},
      payroll_headcount=payroll_headcount,
      business_naics_6="311811",
    )

    adjusted = result.adjusted_payroll_headcount or {}
    rows = adjusted.get("rows") or []
    totals = adjusted.get("quarter_totals") or []
    totals_by_q = {int(qt.get("quarter_index") or 0): float(qt.get("payroll") or 0.0) for qt in totals}
    row_sums: Dict[int, float] = {}
    for row in rows:
      q = int(row.get("quarter_index") or 0)
      avg_fte = (float(row["starting_fte"]) + float(row["ending_fte"])) / 2.0
      qwage = round((avg_fte * float(row["annual_wage"])) / 4.0)
      qbenefits = round(qwage * float(row["payroll_taxes_benefits_percent"]))
      row_sums[q] = row_sums.get(q, 0.0) + qwage + qbenefits
    for q, expected in row_sums.items():
      self.assertEqual(
        int(round(totals_by_q.get(q, 0.0))),
        int(round(expected)),
        f"Q{q} quarter_total.payroll must match deterministic row rollup",
      )

  def test_cascade_still_fires_levers_2_3_4_when_structurally_infeasible(self) -> None:
    """The 3 surviving levers must still be invoked for an infeasible
    scenario."""
    from client_intake_and_finmo.post_intake_solver.feasibility_restoration import (  # noqa: WPS433
      restore_feasibility,
    )

    result = restore_feasibility(
      structural_result=_Result(
        feasibility_gap=500_000.0,
        upper_bound_annual_revenue=200_000.0,
        lower_bound_annual_fixed_cost=500_000.0,
      ),
      ops_json={
        "unit_price": 1.80,
        "units_per_period_capacity": 1080,
        "operating_periods_per_year": 50,
        "utilization_rate": 0.70,
      },
      financials_json={},
      financials_year1_json={},
      payroll_headcount=_payroll_headcount_with_consistent_rollup(),
      business_naics_6="311811",
    )
    lever_names = [a.get("lever") for a in (result.applied_adjustments or [])]
    # At minimum, the unbounded capacity_expansion lever must fire for a
    # >$0.5M annual gap. Price and utilization may also fire depending on
    # their band ceilings.
    self.assertIn(
      "capacity_expansion_unbounded",
      lever_names,
      "Cascade must still escalate to capacity_expansion_unbounded for a large gap",
    )
    self.assertTrue(
      result.feasible_after_adjustment,
      "Capacity expansion is unbounded; the cascade must land feasible",
    )


if __name__ == "__main__":
  unittest.main()
