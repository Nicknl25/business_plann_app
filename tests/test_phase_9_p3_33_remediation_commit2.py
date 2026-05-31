"""Phase 9 P3.33 remediation — Commit 2 (B6).

Economic envelope hardening for all four set_* tools. Each tool now
runs a structural sanity check BEFORE the band check; envelope
violations are returned with prefix "envelope_violation_" so callers
can distinguish them from band violations.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # noqa: E402,E501
  _check_envelope_violations as _stage_ramp_envelope,
)
from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (  # noqa: E402,E501
  _check_envelope_violations as _payroll_envelope,
)
from client_intake_and_finmo.post_intake_amalgamated.tools.set_drivers import (  # noqa: E402,E501
  _check_envelope_violations as _drivers_envelope,
)
from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E402,E501
  _check_envelope_violations as _capex_envelope,
)


# ---------------------------------------------------------------------------
# set_stage_ramp_contract envelope
# ---------------------------------------------------------------------------

class StageRampEnvelopeTest(unittest.TestCase):
  def test_negative_rev_max_rejected(self) -> None:
    contract = {"quarter_ramp_grid": [{"q": 1, "rev_max": -0.5}]}
    v = _stage_ramp_envelope(contract)
    self.assertTrue(any(x["code"] == "envelope_violation_rev_max_negative" for x in v))

  def test_rev_max_nan_rejected(self) -> None:
    contract = {"quarter_ramp_grid": [{"q": 1, "rev_max": float("nan")}]}
    v = _stage_ramp_envelope(contract)
    self.assertTrue(any(x["code"] == "envelope_violation_rev_max_not_finite" for x in v))

  def test_ratio_greater_than_one_rejected(self) -> None:
    contract = {"quarter_ramp_grid": [{"q": 1, "cogs_max": 1.5}]}
    v = _stage_ramp_envelope(contract)
    self.assertTrue(
      any(x["code"] == "envelope_violation_ratio_out_of_unit_interval"
          and x["field"] == "cogs_max" for x in v)
    )

  def test_negative_ratio_rejected(self) -> None:
    contract = {"quarter_ramp_grid": [{"q": 1, "marketing_max": -0.05}]}
    v = _stage_ramp_envelope(contract)
    self.assertTrue(
      any(x["code"] == "envelope_violation_ratio_out_of_unit_interval"
          and x["field"] == "marketing_max" for x in v)
    )

  # P3.41 audit F-C1: deleted test_util_max_below_floor_rejected -- the
  # util_max >= util_floor consistency check was dead (both referenced
  # fields were wrong/nonexistent in the producer's emission shape).
  # The replacement coverage -- max_util ratio bound -- lives in
  # tests/test_p3_41_round1_audit_batch.py::StageRampEnvelopeMaxUtilTest.

  def test_non_monotonic_rev_max_rejected(self) -> None:
    contract = {"quarter_ramp_grid": [
      {"q": 1, "rev_max": 0.5},
      {"q": 2, "rev_max": 0.3},  # decreases
    ]}
    v = _stage_ramp_envelope(contract)
    self.assertTrue(any(x["code"] == "envelope_violation_rev_max_non_monotonic" for x in v))

  def test_clean_contract_no_envelope_violations(self) -> None:
    contract = {"quarter_ramp_grid": [
      {"q": 1, "rev_max": 0.1, "cogs_max": 0.4, "util_max": 0.7, "util_floor": 0.5,
       "ni_floor": -0.1},
      {"q": 2, "rev_max": 0.2, "cogs_max": 0.4, "util_max": 0.7, "util_floor": 0.5,
       "ni_floor": -0.05},
    ]}
    v = _stage_ramp_envelope(contract)
    self.assertEqual(v, [])


# ---------------------------------------------------------------------------
# set_payroll_schedule envelope
# ---------------------------------------------------------------------------

class PayrollEnvelopeTest(unittest.TestCase):
  def test_target_payroll_percent_above_one_rejected(self) -> None:
    contract = {"target_payroll_percent_of_revenue": 1.5}
    v = _payroll_envelope(contract)
    self.assertTrue(any(
      x["code"] == "envelope_violation_payroll_target_out_of_unit_interval"
      for x in v
    ))

  # P3.41 audit F-C2: deleted test_negative_headcount_rejected,
  # test_fractional_headcount_rejected, test_negative_wage_rejected --
  # the roles/headcount/wage_per_employee arm was dead (no producer
  # emits any of those fields anywhere in python/client_intake_and_finmo/).
  # Adding equivalent invariants on the real payroll_headcount_grid
  # shape (starting_fte/ending_fte/hires) is a separate design task
  # outside the audit batch.

  def test_clean_payroll_no_violations(self) -> None:
    contract = {
      "target_payroll_percent_of_revenue": 0.35,
      "roles": [{"id": "eng", "headcount": 5, "wage_per_employee": 8000}],
      "schedule": [{"q": 1, "total": 40000}],
    }
    self.assertEqual(_payroll_envelope(contract), [])


# ---------------------------------------------------------------------------
# set_drivers envelope
# ---------------------------------------------------------------------------

class DriversEnvelopeTest(unittest.TestCase):
  def test_negative_anchor_rejected(self) -> None:
    anchors = {"expenses::Cost of Goods Sold": {"q1": -0.1, "q11": 0.4, "q20": 0.4}}
    v = _drivers_envelope(anchors)
    self.assertTrue(any(
      x["code"] == "envelope_violation_driver_anchor_out_of_unit_interval"
      and x["anchor"] == "q1"
      for x in v
    ))

  def test_anchor_above_one_rejected(self) -> None:
    anchors = {"expenses::Marketing": {"q1": 0.05, "q11": 0.1, "q20": 1.5}}
    v = _drivers_envelope(anchors)
    self.assertTrue(any(
      x["code"] == "envelope_violation_driver_anchor_out_of_unit_interval"
      and x["anchor"] == "q20"
      for x in v
    ))

  def test_nan_anchor_rejected(self) -> None:
    anchors = {"expenses::Research & Development": {"q1": float("nan"), "q11": 0.05, "q20": 0.05}}
    v = _drivers_envelope(anchors)
    self.assertTrue(any(x["code"] == "envelope_violation_driver_anchor_not_finite" for x in v))

  def test_clean_anchors_no_violations(self) -> None:
    anchors = {
      "expenses::Cost of Goods Sold": {"q1": 0.45, "q11": 0.40, "q20": 0.38},
      "expenses::Marketing": {"q1": 0.10, "q11": 0.10, "q20": 0.10},
    }
    self.assertEqual(_drivers_envelope(anchors), [])


# ---------------------------------------------------------------------------
# set_capex_rd_balance_seed envelope
# ---------------------------------------------------------------------------

class CapexBalanceSeedEnvelopeTest(unittest.TestCase):
  # P3.41 NexGen E2E iter 8: envelope check now reads maintenance_rate
  # (canonical ratio form, matches every downstream consumer) rather than
  # the percent-form maintenance_capex_percent. Tests updated to assert
  # the corrected field.
  def test_maintenance_capex_above_one_rejected(self) -> None:
    mc = {"maintenance_rate": 1.5}
    v = _capex_envelope(mc, None, None)
    self.assertTrue(any(
      x["code"] == "envelope_violation_maintenance_capex_out_of_unit_interval"
      for x in v
    ))

  def test_maintenance_capex_negative_rejected(self) -> None:
    mc = {"maintenance_rate": -0.1}
    v = _capex_envelope(mc, None, None)
    self.assertTrue(any(
      x["code"] == "envelope_violation_maintenance_capex_out_of_unit_interval"
      for x in v
    ))

  def test_balance_sheet_seed_negative_days_rejected(self) -> None:
    bs = {"balance_sheet_seed_grid": [
      {"lever_id": "balance_sheet::Accounts Receivable Days",
       "applicable": True, "seed_value": -10},
    ]}
    v = _capex_envelope(None, None, bs)
    self.assertTrue(any(
      x["code"] == "envelope_violation_balance_sheet_seed_negative"
      for x in v
    ))

  def test_balance_sheet_seed_nan_rejected(self) -> None:
    bs = {"balance_sheet_seed_grid": [
      {"lever_id": "balance_sheet::Inventory Days",
       "applicable": True, "seed_value": float("inf")},
    ]}
    v = _capex_envelope(None, None, bs)
    self.assertTrue(any(
      x["code"] == "envelope_violation_balance_sheet_seed_not_finite"
      for x in v
    ))

  def test_non_applicable_row_not_checked(self) -> None:
    bs = {"balance_sheet_seed_grid": [
      {"lever_id": "balance_sheet::Inventory Days",
       "applicable": False, "seed_value": -999},
    ]}
    v = _capex_envelope(None, None, bs)
    # Non-applicable rows skip envelope check (they're not used).
    self.assertEqual(v, [])

  def test_clean_payloads_no_violations(self) -> None:
    # P3.41 NexGen E2E iter 8: maintenance_rate (ratio) replaces
    # maintenance_capex_percent (percent) as the envelope-checked field.
    mc = {"maintenance_rate": 0.02}
    bs = {"balance_sheet_seed_grid": [
      {"lever_id": "balance_sheet::AR Days",
       "applicable": True, "seed_value": 30},
    ]}
    self.assertEqual(_capex_envelope(mc, None, bs), [])


if __name__ == "__main__":
  unittest.main()
