"""Phase 9 P3.10 NexGen iter 1 fix — smoke tests for the debt schedule
no longer pulling amortization shape from intake.

Verifies:
  - Intake `annual_principal_payment` is NOT consulted by
    build_debt_schedule_plan (no longer in source).
  - Schedule emits straight-line amortization
    (ceil(opening / remaining_quarters)) regardless of intake's
    annual_principal_payment value.
  - The legacy intake-defending hard-fail
    "debt_schedule_quarterly_minimum_zero" is gone.
  - The legacy private helper _annual_principal_from_financials is gone.
  - Output shape no longer leaks intake-derived bookkeeping fields
    (annual_principal_payment, annual_principal_source,
    quarterly_minimum_principal, contractual_quarterly_floor,
    principal_source).
"""

from __future__ import annotations

import math
import os
import pathlib
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


SCHEDULE_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_debt_schedule"
  / "schedule.py"
)


def _model_input_with_seed(opening_seed: int) -> dict:
  """Minimal model_input_json that satisfies build_debt_schedule_plan's
  preconditions (opening seed + SBA-backed interest rate policy)."""
  return {
    "sections": {
      "schedules": {
        "debt_opening_balance_seed": opening_seed,
      },
    },
    "derived_driver_policies": {
      "debt_interest_rate_policy": {
        "annual_rate_decimal": 0.085,
        "source_detail": {
          "source": "sba_loan_7a_raw",
          "annual_rate_decimal": 0.085,
        },
      },
    },
  }


class NexGenIter1DebtScheduleNoIntakeOverrideTest(unittest.TestCase):
  def test_intake_field_not_referenced_in_schedule_source(self) -> None:
    """`annual_principal_payment` should no longer appear anywhere in
    the schedule module — neither as a financials lookup nor in the
    output dicts."""
    text = SCHEDULE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "annual_principal_payment", text,
      "schedule.py must not consume or emit annual_principal_payment "
      "(intake field) — Q1-Q20 amortization is the schedule's job",
    )

  def test_legacy_intake_helper_removed(self) -> None:
    text = SCHEDULE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "_annual_principal_from_financials", text,
      "_annual_principal_from_financials helper must be removed",
    )

  def test_legacy_intake_defending_hard_fail_removed(self) -> None:
    text = SCHEDULE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "debt_schedule_quarterly_minimum_zero", text,
      "the intake-defending hard-fail must be removed",
    )

  def test_contractual_quarterly_floor_concept_removed(self) -> None:
    text = SCHEDULE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "contractual_quarterly_floor", text,
      "contractual_quarterly_floor is dead — minimum is straight-line only",
    )

  def test_minimum_principal_is_pure_straight_line(self) -> None:
    """End-to-end: with $300K opening debt and 20-quarter horizon,
    schedule emits ceil(300000/20) = 15000 in Q1, then ceil of the
    declining balance for each subsequent quarter."""
    from client_intake_and_finmo.post_intake_debt_schedule.schedule import (  # noqa: WPS433
      build_debt_schedule_plan,
    )

    HORIZON = 20
    opening_seed = 300_000
    model_input_json = _model_input_with_seed(opening_seed)
    # Intake claims a wildly different annual principal — schedule MUST
    # ignore this entirely and produce straight-line amortization.
    financials_json = {
      "annual_principal_payment": 999_999_999,
      "total_debt_outstanding": opening_seed,
    }

    plan = build_debt_schedule_plan(
      model_input_json=model_input_json,
      finmo_payload=None,
      financials_json=financials_json,
      selected_cash_strategy=None,
      contract_name="cash_strategy_review",
    )

    self.assertEqual(plan.get("status"), "ready")
    rows = plan.get("rows") or []
    self.assertEqual(len(rows), HORIZON)

    # Q1 expectation: ceil(300000/20) = 15000, closing 285000.
    q1 = rows[0]
    self.assertEqual(q1["opening_debt"], opening_seed)
    self.assertEqual(q1["amortizing_minimum_principal"], 15000)
    self.assertEqual(q1["minimum_principal_payment"], 15000)
    self.assertEqual(q1["total_principal_payment"], 15000)
    self.assertEqual(q1["closing_debt"], 285_000)

    # Walk forward — every quarter must be ceil(opening/remaining).
    opening = opening_seed
    for q in range(1, HORIZON + 1):
      remaining = HORIZON - q + 1
      expected_min = int(math.ceil(opening / remaining))
      row = rows[q - 1]
      self.assertEqual(row["amortizing_minimum_principal"], expected_min,
                       f"Q{q} amortizing_minimum mismatch")
      self.assertEqual(row["total_principal_payment"], expected_min,
                       f"Q{q} total_principal_payment mismatch")
      opening = row["closing_debt"]

    # By Q20, the loan is fully paid off.
    self.assertEqual(rows[-1]["closing_debt"], 0)

  def test_intake_overstated_principal_does_not_change_schedule(self) -> None:
    """Sweep: vary intake's annual_principal_payment from 0 to 10x the
    debt — the schedule is unchanged because intake no longer feeds in."""
    from client_intake_and_finmo.post_intake_debt_schedule.schedule import (  # noqa: WPS433
      build_debt_schedule_plan,
    )

    opening_seed = 200_000
    model_input_json = _model_input_with_seed(opening_seed)

    schedules = []
    for ap in (0, 1_000, 50_000, 200_000, 2_000_000):
      financials_json = {
        "annual_principal_payment": ap,
        "total_debt_outstanding": opening_seed,
      }
      plan = build_debt_schedule_plan(
        model_input_json=model_input_json,
        finmo_payload=None,
        financials_json=financials_json,
        selected_cash_strategy=None,
        contract_name="cash_strategy_review",
      )
      schedules.append([row["total_principal_payment"] for row in plan["rows"]])

    # Every produced principal series must be identical.
    for s in schedules[1:]:
      self.assertEqual(s, schedules[0],
                       "schedule must be invariant to intake annual_principal_payment")


if __name__ == "__main__":
  unittest.main()
