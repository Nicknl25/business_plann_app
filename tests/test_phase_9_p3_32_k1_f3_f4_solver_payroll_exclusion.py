"""Phase 9 P3.32 K1 (F3+F4) — regression guard for target-solver
Payroll authority exclusion.

P3.31 audit Leak B: the restoration target-solver writes whatever
lever_id appears in failing realism rows' primary_levers. Multiple
realism rows previously listed "expenses::Payroll"
(lookup.py:544, 605, 1005, 1116 + secondary at 1033, 1077). Solver
bypassed Handler C's canonical Payroll authority.

P3.32 K1 F3 — solver-side closure:
  - Adds _HANDLER_C_OWNED_LEVER_IDS = frozenset({"expenses::Payroll"})
    to target_solver.py.
  - _ALL_HANDLER_OWNED_LEVER_IDS = _CASH_PASS_OWNED_LEVER_IDS |
    _HANDLER_C_OWNED_LEVER_IDS — the union the solver entry check
    consults.
  - _driver_kind_for_lever returns "handler_c_owned" for
    expenses::Payroll (analogous to cash_pass_owned).
  - solve_for_target raises CashPassLeverViolation (re-used exception
    type, distinguishing message) if any handler-c-owned lever
    appears in the driver_lever_ids list.
  - restoration_loop._resolve_driver_bounds_from_primary_levers
    skips Payroll levers the same way it skips cash-pass-owned
    levers — so stale SQL data with Payroll in primary_levers
    becomes a silent no-op rather than a runtime violation.

P3.32 K1 F4 — config-side annotation:
  - Removed "expenses::Payroll" from primary_levers in lookup.py
    rows 544 (payroll_percent_of_revenue), 605 (ebitda_margin),
    1005 (ebitda_positive_by_q11), 1116
    (fixed_cost_burden_reduced_or_scaled_by_q11).
  - Removed "expenses::Payroll" from secondary_levers in lookup.py
    rows 1033 (ebitda_recovery_trend_q5_q11), 1077
    (ebitda_margin_q20_holds_or_improves_vs_q11).
  - Notes annotations on each row mark the K1 F4 change so future
    operators understand why Payroll is absent.

This file pins both surfaces. F3 is the structural safeguard
(solver rejects/skips Payroll even if SQL drifts back); F4 is the
clean state of the in-code defaults (the SQL bootstrap upsert
syncs from these).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


_PAYROLL_LEVER_ID = "expenses::Payroll"


class TestTargetSolverHandlerOwnedSets(unittest.TestCase):
  """F3 surface 1: the target_solver.py module-level sets."""

  def test_handler_c_owned_set_contains_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _HANDLER_C_OWNED_LEVER_IDS,
    )
    self.assertIn(_PAYROLL_LEVER_ID, _HANDLER_C_OWNED_LEVER_IDS)

  def test_all_handler_owned_set_is_union(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _ALL_HANDLER_OWNED_LEVER_IDS,
      _CASH_PASS_OWNED_LEVER_IDS,
      _HANDLER_C_OWNED_LEVER_IDS,
    )
    self.assertEqual(
      _ALL_HANDLER_OWNED_LEVER_IDS,
      _CASH_PASS_OWNED_LEVER_IDS | _HANDLER_C_OWNED_LEVER_IDS,
    )
    self.assertIn(_PAYROLL_LEVER_ID, _ALL_HANDLER_OWNED_LEVER_IDS)

  def test_cash_pass_set_unchanged_by_k1(self) -> None:
    """K1 F3 must not touch the cash-pass-owned set; that authority
    boundary is independent (cash strategy)."""
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _CASH_PASS_OWNED_LEVER_IDS,
    )
    self.assertEqual(
      _CASH_PASS_OWNED_LEVER_IDS,
      frozenset({
        "balance_sheet::Owner's Capital",
        "balance_sheet::Other Equity",
        "balance_sheet::Distributions",
        "balance_sheet::Short Term Debt (% of LTD)",
        "schedules::Debt Issuance (New Borrowing)",
        "schedules::Debt Repayment (Scheduled)",
      }),
    )


class TestDriverKindForPayroll(unittest.TestCase):
  """F3 surface 2: _driver_kind_for_lever classification."""

  def test_payroll_classified_handler_c_owned(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _driver_kind_for_lever,
    )
    self.assertEqual(_driver_kind_for_lever(_PAYROLL_LEVER_ID), "handler_c_owned")

  def test_other_quarter_currency_levers_unchanged(self) -> None:
    """Lease is still quarter_currency — Payroll was the only
    handler-c-owned lever; Lease stays solver-authored."""
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _driver_kind_for_lever,
    )
    self.assertEqual(_driver_kind_for_lever("expenses::Lease"), "quarter_currency")

  def test_cash_pass_levers_still_classified_cash_pass_owned(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _driver_kind_for_lever,
    )
    self.assertEqual(
      _driver_kind_for_lever("balance_sheet::Owner's Capital"),
      "cash_pass_owned",
    )


class TestSolveForTargetRejectsHandlerCOwnedLevers(unittest.TestCase):
  """F3 surface 3: solve_for_target entry validation rejects
  any handler-c-owned lever in the driver_lever_ids list."""

  def test_solve_for_target_raises_on_payroll_in_driver_list(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      solve_for_target,
      CashPassLeverViolation,
      HORIZON_QUARTERS_DEFAULT,
    )
    with self.assertRaises(CashPassLeverViolation) as ctx:
      solve_for_target(
        target_metric="ebitda_margin",
        target_ramp=[0.0] * HORIZON_QUARTERS_DEFAULT,
        driver_lever_ids=[_PAYROLL_LEVER_ID, "expenses::Cost of Goods Sold"],
        driver_bounds={},
        model_input={"sections": {}},
        build_finmo=lambda mi: {},
      )
    msg = str(ctx.exception)
    self.assertIn("handler_c_owned_lever_in_driver_list", msg)
    self.assertIn(_PAYROLL_LEVER_ID, msg)


class TestRestorationLoopFiltersPayrollFromBounds(unittest.TestCase):
  """F3 surface 4: restoration_loop bounds resolver skips
  Payroll levers before they reach the solver."""

  def test_resolver_imports_handler_c_owned_set(self) -> None:
    """The bounds resolver must import _HANDLER_C_OWNED_LEVER_IDS
    so it can filter primary_levers entries."""
    import os
    here = os.path.abspath(os.path.dirname(__file__))
    path = os.path.join(
      here, os.pardir, "python", "client_intake_and_finmo",
      "post_intake_target_solver", "restoration_loop.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      source = fh.read()
    self.assertIn("_HANDLER_C_OWNED_LEVER_IDS", source)
    self.assertIn(
      "if lid in _HANDLER_C_OWNED_LEVER_IDS:", source,
      msg="restoration_loop must skip Payroll levers in primary_levers iteration",
    )


class TestRealismConfigPrimaryLeversExcludePayroll(unittest.TestCase):
  """F4 surface: in-code realism row defaults must not list
  Payroll in primary_levers. Tests the rows by metric_key so
  refactors / reordering don't drift."""

  @staticmethod
  def _rows_by_metric() -> dict:
    from client_intake_and_finmo.post_intake_realism import lookup as _lookup  # noqa: WPS433
    return {row.get("metric_key"): row for row in _lookup._DEFAULT_REALISM_CHECK_ROWS}

  def test_payroll_percent_of_revenue_primary_levers_excludes_payroll(self) -> None:
    row = self._rows_by_metric().get("payroll_percent_of_revenue") or {}
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("primary_levers") or [])

  def test_ebitda_margin_primary_levers_excludes_payroll(self) -> None:
    row = self._rows_by_metric().get("ebitda_margin") or {}
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("primary_levers") or [])
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("secondary_levers") or [])

  def test_ebitda_positive_by_q11_primary_levers_excludes_payroll(self) -> None:
    row = self._rows_by_metric().get("ebitda_positive_by_q11") or {}
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("primary_levers") or [])
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("secondary_levers") or [])

  def test_ebitda_recovery_trend_q5_q11_excludes_payroll(self) -> None:
    row = self._rows_by_metric().get("ebitda_recovery_trend_q5_q11") or {}
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("primary_levers") or [])
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("secondary_levers") or [])

  def test_ebitda_margin_q20_holds_or_improves_excludes_payroll(self) -> None:
    row = self._rows_by_metric().get("ebitda_margin_q20_holds_or_improves_vs_q11") or {}
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("primary_levers") or [])
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("secondary_levers") or [])

  def test_fixed_cost_burden_excludes_payroll(self) -> None:
    row = self._rows_by_metric().get("fixed_cost_burden_reduced_or_scaled_by_q11") or {}
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("primary_levers") or [])
    self.assertNotIn(_PAYROLL_LEVER_ID, row.get("secondary_levers") or [])

  def test_payroll_percent_of_revenue_still_active(self) -> None:
    """K1 F4 removes Payroll from primary_levers but the metric
    itself stays active — it's still a reasonableness signal,
    just remediated via Handler C, not via direct solver writes."""
    row = self._rows_by_metric().get("payroll_percent_of_revenue") or {}
    self.assertEqual(row.get("metric_key"), "payroll_percent_of_revenue")
    self.assertEqual(row.get("governs_model_input_lever_id"), _PAYROLL_LEVER_ID,
                     msg="The metric still tracks Payroll — only the SOLVER lever wiring changed.")


if __name__ == "__main__":
  unittest.main()
