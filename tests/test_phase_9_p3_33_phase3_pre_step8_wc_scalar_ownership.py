"""Phase 9 P3.33 Phase 3 pre-step-8 — WC scalar ownership migration.

Acceptance tests for the migration:

  - cohort_bands_table._SECTION_LEVERS no longer lists WC levers under
    'drivers'; they live under a new 'balance_sheet' key.
  - set_drivers._DRIVER_LEVER_IDS no longer contains WC lever_ids.
  - handler.py no longer defines the deleted dead-code symbols
    (_WC_KEY_TO_LEVER_ID, _write_gpt_authored_working_capital_values).
  - set_capex_rd_balance_seed accepts WC overrides under the
    "working_capital_days" sub-key and routes them into the
    balance_sheet_seed_grid rows.
  - revise_capex_rd_balance_seed round-trips a WC patch through to
    the setter.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class CohortBandsSectionLeversTest(unittest.TestCase):
  def test_wc_levers_moved_from_drivers_to_balance_sheet(self) -> None:
    from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (
      _SECTION_LEVERS,
    )
    drivers = [lever for lever, _metric in _SECTION_LEVERS["drivers"]]
    for wc in (
      "balance_sheet::Accounts Receivable Days",
      "balance_sheet::Accounts Payable Days",
      "balance_sheet::Inventory Days",
    ):
      self.assertNotIn(
        wc, drivers,
        msg=f"{wc} must no longer appear in drivers section",
      )
    self.assertIn("balance_sheet", _SECTION_LEVERS)
    balance_sheet = [lever for lever, _metric in _SECTION_LEVERS["balance_sheet"]]
    self.assertEqual(set(balance_sheet), {
      "balance_sheet::Accounts Receivable Days",
      "balance_sheet::Accounts Payable Days",
      "balance_sheet::Inventory Days",
    })


class SetDriversLeverListTest(unittest.TestCase):
  def test_driver_lever_ids_only_pnl_levers(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_drivers import (
      _DRIVER_LEVER_IDS,
    )
    self.assertEqual(set(_DRIVER_LEVER_IDS), {
      "expenses::Cost of Goods Sold",
      "expenses::Research & Development",
      "expenses::General & Administrative",
      "expenses::Marketing",
    })


class HandlerDeadSymbolsRemovedTest(unittest.TestCase):
  def test_wc_writer_and_key_map_deleted(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler import handler as h
    self.assertFalse(hasattr(h, "_WC_KEY_TO_LEVER_ID"))
    self.assertFalse(hasattr(h, "_write_gpt_authored_working_capital_values"))
    # The realism-gate constant survives (still used in compute_metrics_to_mute).
    self.assertTrue(hasattr(h, "GPT_AUTHORED_WORKING_CAPITAL_LEVER_IDS"))


class SetCapexRdBalanceSeedWCOverridesTest(unittest.TestCase):
  """Round-trip the working_capital_days override path."""

  def _fake_bs_payload_with_grid(self):
    return {
      "contract_version": "balance_sheet_contextual_seed_proposal_v1",
      "decision_source": "python_proposer",
      "balance_sheet_seed_grid": [
        {"lever_id": "balance_sheet::Accounts Receivable Days",
         "applicable": True, "seed_value": 45.0, "value_kind": "days"},
        {"lever_id": "balance_sheet::Accounts Payable Days",
         "applicable": True, "seed_value": 30.0, "value_kind": "days"},
        {"lever_id": "balance_sheet::Inventory Days",
         "applicable": False, "seed_value": 0.0, "value_kind": "days"},
      ],
      "naics_6": "722511",
    }

  def _build_call_kwargs(self, *, overrides=None, conn=None):
    fake_bs = self._fake_bs_payload_with_grid()
    return {
      "conn": conn,
      "draft_id": "d", "planning_run_id": "r",
      "overrides": overrides,
      "business_facts": {}, "ops_json": {}, "financials_json": {},
      "financials_year1_json": {}, "model_input_json": {}, "finmo_json": {},
      "_maintenance": lambda inputs: {"maintenance_capex_percent": 0.04},
      "_r_and_d": lambda inputs: {"r_and_d_enabled": True},
      "_balance_sheet": lambda inputs: fake_bs,
    }

  def test_wc_override_updates_grid_row_seed_value(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      set_capex_rd_balance_seed,
    )
    env = set_capex_rd_balance_seed(**self._build_call_kwargs(overrides={
      "working_capital_days": {
        "balance_sheet::Accounts Receivable Days": 60.0,
      },
    }))
    self.assertTrue(env["accepted"])
    grid = env["payload"]["balance_sheet_seed"]["balance_sheet_seed_grid"]
    ar_row = next(r for r in grid if r["lever_id"] == "balance_sheet::Accounts Receivable Days")
    self.assertAlmostEqual(ar_row["seed_value"], 60.0)
    # Audit record present.
    audit = [a for a in env["overrides_applied"]
             if a.get("field") == "balance_sheet::Accounts Receivable Days"]
    self.assertEqual(len(audit), 1)
    self.assertAlmostEqual(audit[0]["applied"], 60.0)

  def test_wc_override_unknown_lever_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      set_capex_rd_balance_seed,
    )
    env = set_capex_rd_balance_seed(**self._build_call_kwargs(overrides={
      "working_capital_days": {"expenses::Cost of Goods Sold": 0.65},
    }))
    self.assertFalse(env["accepted"])
    codes = [v["code"] for v in env["violations"]]
    self.assertIn("wc_override_unknown_lever", codes)

  def test_wc_override_non_applicable_lever_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      set_capex_rd_balance_seed,
    )
    # Inventory Days is applicable=False in the fake bs payload above —
    # a service business analog.
    env = set_capex_rd_balance_seed(**self._build_call_kwargs(overrides={
      "working_capital_days": {"balance_sheet::Inventory Days": 30.0},
    }))
    self.assertFalse(env["accepted"])
    codes = [v["code"] for v in env["violations"]]
    self.assertIn("wc_override_lever_not_applicable", codes)

  def test_wc_override_non_numeric_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      set_capex_rd_balance_seed,
    )
    env = set_capex_rd_balance_seed(**self._build_call_kwargs(overrides={
      "working_capital_days": {"balance_sheet::Accounts Receivable Days": "banana"},
    }))
    self.assertFalse(env["accepted"])
    codes = [v["code"] for v in env["violations"]]
    self.assertIn("wc_override_non_numeric", codes)


class ReviseCapexRdBalanceSeedWCRoundTripTest(unittest.TestCase):
  def test_revise_path_forwards_wc_override_to_setter(self) -> None:
    """revise_capex_rd_balance_seed deep-merges its patch with current
    overrides and calls set_capex_rd_balance_seed. A WC-day patch must
    surface in the setter call's overrides argument under
    'working_capital_days'."""
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_capex_rd_balance_seed import (  # noqa: E501
      revise_capex_rd_balance_seed,
    )
    seen = {}
    def fake_setter(**kwargs):
      seen.update(kwargs)
      return {"accepted": True, "section": "capex_rd_balance_seed",
              "payload": {}, "violations": []}
    env = revise_capex_rd_balance_seed(
      current_overrides={"maintenance_capex_percent": 0.04},
      patch={
        "working_capital_days": {
          "balance_sheet::Accounts Receivable Days": 55.0,
        },
      },
      _set_capex_rd_balance_seed=fake_setter,
    )
    self.assertTrue(env["accepted"])
    fwd_overrides = seen["overrides"]
    self.assertEqual(
      fwd_overrides["working_capital_days"],
      {"balance_sheet::Accounts Receivable Days": 55.0},
    )
    # The prior overrides are preserved.
    self.assertEqual(fwd_overrides["maintenance_capex_percent"], 0.04)


if __name__ == "__main__":
  unittest.main()
