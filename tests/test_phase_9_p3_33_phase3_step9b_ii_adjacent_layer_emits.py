"""Phase 9 P3.33 Phase 3 step 9b part 2 — adjacent-layer emit
instrumentation tests.

Covers the emits added in 9b-ii to:
  - set_capex_rd_balance_seed(contract=None / overrides=None) →
    ROUND1_CAPEX_RD_BALANCE_SEED_OK / FAIL.
  - set_stage_ramp_contract(contract=None) →
    ROUND1_STAGE_RAMP_OK / FAIL.
  - set_payroll_schedule(contract=None, with Handler C internal
    invocation) → ROUND1_PAYROLL_OK.
  - populate_cohort_bands_for_run → COHORT_BANDS_STARTED +
    COHORT_BANDS_COMPLETED with summary counts.
  - build_mirror → MIRROR_BUILD_COMPLETED with sections_populated /
    bands_loaded counts (or MIRROR_BUILD_NO_BANDS when none load).

Cohort_bands + mirror tests use a fake conn that captures every
diagnostic INSERT params tuple; set_* tests inject a fake emit via
the post_intake_diagnostics safe_emit module-level binding.
safe_emit calls land on the shared fake conn for inspection.

(The orchestrator's baseline_finmo_sync emits are covered by an
integration-shape source-check; the call site uses _diag_safe_emit
with FINMO_SYNC_STARTED/COMPLETED + diagnostic_data.)
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List, Optional


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402,E501
  EventCode, PhaseCode, Status,
)


class _FakeCursor:
  def __init__(self, store):
    self._store = store
    self.lastrowid = None

  def execute(self, sql, params=None):
    sql_low = sql.strip().lower()
    self._store["calls"].append((sql, params))
    if sql_low.startswith("create table"):
      self._store["create_sql"] = sql
      return
    if sql_low.startswith("insert"):
      self._store["rows"].append(params)
      self._store["next_id"] += 1
      self.lastrowid = self._store["next_id"]
      return

  def fetchall(self):
    return list(self._store.get("rows", []))

  def close(self):
    pass


class _FakeConn:
  def __init__(self):
    self._store = {"calls": [], "rows": [], "next_id": 0}

  def cursor(self, dictionary=False):
    return _FakeCursor(self._store)

  def commit(self):
    pass

  def diagnostics(self) -> List[tuple]:
    """Return the list of INSERT params tuples (each represents one
    diagnostic row in the order columns are declared)."""
    return [r for r in self._store["rows"] if isinstance(r, tuple)]

  def events_emitted(self) -> List[str]:
    # Column 4 (0-indexed 3) is event_code in the
    # post_intake_run_diagnostics INSERT order.
    return [r[3] for r in self.diagnostics()]


# ---------------------------------------------------------------------------
# set_capex_rd_balance_seed emits
# ---------------------------------------------------------------------------

class SetCapexRdBalanceSeedEmitTest(unittest.TestCase):
  def test_round1_emits_ok_on_accept(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      set_capex_rd_balance_seed,
    )
    conn = _FakeConn()
    res = set_capex_rd_balance_seed(
      conn=conn, draft_id="d", planning_run_id="r",
      overrides=None,
      business_facts={}, ops_json={}, financials_json={},
      financials_year1_json={}, model_input_json={}, finmo_json={},
      _maintenance=lambda inputs: {"maintenance_capex_percent": 0.04},
      _r_and_d=lambda inputs: {"r_and_d_enabled": True},
      _balance_sheet=lambda inputs: {"balance_sheet_seed_grid": []},
    )
    self.assertTrue(res["accepted"])
    self.assertIn(
      EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_OK.value, conn.events_emitted()
    )

  def test_round1_emits_fail_on_builder_exception(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      set_capex_rd_balance_seed,
    )
    conn = _FakeConn()
    def boom(_inputs): raise RuntimeError("boom")
    res = set_capex_rd_balance_seed(
      conn=conn, draft_id="d", planning_run_id="r",
      overrides=None,
      business_facts={}, ops_json={}, financials_json={},
      financials_year1_json={}, model_input_json={}, finmo_json={},
      _maintenance=boom,
      _r_and_d=lambda inputs: {"r_and_d_enabled": True},
      _balance_sheet=lambda inputs: {"balance_sheet_seed_grid": []},
    )
    self.assertFalse(res["accepted"])
    self.assertIn(
      EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_FAIL.value, conn.events_emitted()
    )

  def test_overrides_path_does_not_emit_round1(self) -> None:
    """When overrides are supplied, the call is a cascade revision —
    the SessionDriver's CASCADE_PROPOSAL_* emits cover it. No
    duplicate ROUND1_CAPEX_RD_BALANCE_SEED emit."""
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      set_capex_rd_balance_seed,
    )
    conn = _FakeConn()
    set_capex_rd_balance_seed(
      conn=conn, draft_id="d", planning_run_id="r",
      overrides={"maintenance_capex": {"some_field": 0.05}},
      business_facts={}, ops_json={}, financials_json={},
      financials_year1_json={}, model_input_json={}, finmo_json={},
      _maintenance=lambda inputs: {"maintenance_capex_percent": 0.04},
      _r_and_d=lambda inputs: {"r_and_d_enabled": True},
      _balance_sheet=lambda inputs: {"balance_sheet_seed_grid": []},
    )
    self.assertNotIn(
      EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_OK.value, conn.events_emitted()
    )
    self.assertNotIn(
      EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_FAIL.value, conn.events_emitted()
    )


# ---------------------------------------------------------------------------
# set_stage_ramp_contract emits
# ---------------------------------------------------------------------------

class SetStageRampEmitTest(unittest.TestCase):
  def _build_kwargs(self, *, conn):
    return dict(
      conn=conn, draft_id="d", planning_run_id="r",
      contract=None,
      business_facts={"business_stage": "operational"},
      ops_json={}, financials_json={}, financials_year1_json={},
      people_json={}, planning_mode="operational",
      planning_mode_reason="test",
      model_input_json={}, finmo_json={},
      r_and_d_applicability={"r_and_d_enabled": True},
      expected_stage_family="operational",
      _builder=lambda **_: {
        "stage_family": "operational",
        "planning_mode": "operational",
      },
      _validator=lambda **_: None,
    )

  def test_round1_emits_ok_on_accept(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # noqa: E501
      set_stage_ramp_contract,
    )
    conn = _FakeConn()
    res = set_stage_ramp_contract(**self._build_kwargs(conn=conn))
    self.assertTrue(res["accepted"])
    self.assertIn(EventCode.ROUND1_STAGE_RAMP_OK.value, conn.events_emitted())

  def test_round1_emits_fail_on_validator_violation(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # noqa: E501
      set_stage_ramp_contract,
    )
    conn = _FakeConn()
    kw = self._build_kwargs(conn=conn)
    def bad_validator(**_):
      raise RuntimeError("stage_ramp_violation_for_test")
    kw["_validator"] = bad_validator
    res = set_stage_ramp_contract(**kw)
    self.assertFalse(res["accepted"])
    self.assertIn(EventCode.ROUND1_STAGE_RAMP_FAIL.value, conn.events_emitted())

  def test_contract_supplied_path_does_not_emit_round1(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # noqa: E501
      set_stage_ramp_contract,
    )
    conn = _FakeConn()
    kw = self._build_kwargs(conn=conn)
    kw["contract"] = {"stage_family": "operational"}
    set_stage_ramp_contract(**kw)
    self.assertNotIn(EventCode.ROUND1_STAGE_RAMP_OK.value, conn.events_emitted())
    self.assertNotIn(EventCode.ROUND1_STAGE_RAMP_FAIL.value, conn.events_emitted())


# ---------------------------------------------------------------------------
# set_payroll_schedule emits
# ---------------------------------------------------------------------------

class SetPayrollScheduleEmitTest(unittest.TestCase):
  def test_round1_emits_ok_via_handler_c(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (  # noqa: E501
      set_payroll_schedule,
    )
    conn = _FakeConn()
    fake_handler_c = lambda **_: {
      "payroll_headcount_contract": {"some_field": "ok"},
    }
    fake_validator = lambda payload: {"some_field": "ok"}
    fake_builder = lambda **_: {"built": True}
    res = set_payroll_schedule(
      conn=conn, draft_id="d", planning_run_id="r",
      contract=None,
      business_facts={}, ops_json={}, people_json={},
      financials_json={}, financials_year1_json={},
      model_input_json={}, finmo_json={},
      stage_ramp_contract={}, planning_mode="operational",
      planning_mode_reason="test",
      _handler_c_author=fake_handler_c,
      _validator=fake_validator,
      _builder=fake_builder,
    )
    self.assertTrue(res["accepted"])
    self.assertEqual(res["decision_source"], "handler_c_internal_authoring")
    self.assertIn(EventCode.ROUND1_PAYROLL_OK.value, conn.events_emitted())


# ---------------------------------------------------------------------------
# populate_cohort_bands_for_run emits
# ---------------------------------------------------------------------------

class CohortBandsPopulatorEmitTest(unittest.TestCase):
  def test_started_and_completed_emitted_with_summary(self) -> None:
    from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # noqa: E501
      populate_cohort_bands_for_run,
    )
    conn = _FakeConn()
    # No real DB is configured; resolve_cohort_band will return None
    # for every (section, lever) pair, so summary entries land with
    # resolved=0/skipped=<count>. The emit pair is what we want to
    # observe.
    summary = populate_cohort_bands_for_run(
      conn,
      draft_id="d", planning_run_id="r",
      business_profile={"naics_6": "722511"},
    )
    events = conn.events_emitted()
    self.assertIn(EventCode.COHORT_BANDS_STARTED.value, events)
    self.assertIn(EventCode.COHORT_BANDS_COMPLETED.value, events)
    self.assertIsInstance(summary, dict)
    self.assertGreater(len(summary), 0)


# ---------------------------------------------------------------------------
# build_mirror emits
# ---------------------------------------------------------------------------

class BuildMirrorEmitTest(unittest.TestCase):
  def test_no_bands_emits_no_bands_event_then_fail_fasts(self) -> None:
    """Step 9d added a FAIL_MIRROR_BANDS_UNRESOLVED guard: when conn +
    ids are present (i.e. a real run) and the bands payload is empty,
    that's a fail-fast. The diagnostic emit still fires *before* the
    raise so observability captures the no-bands event."""
    from client_intake_and_finmo.post_intake_amalgamated.mirror import (
      build_mirror,
    )
    conn = _FakeConn()
    with self.assertRaises(RuntimeError) as ctx:
      build_mirror(
        conn, draft_id="d", planning_run_id="r",
        business_facts={"naics_6": "722511"},
        plan_state={}, load_bands=False,
      )
    self.assertIn("fail_mirror_bands_unresolved", str(ctx.exception))
    # The MIRROR_BUILD_NO_BANDS emit fired before the guard tripped.
    self.assertIn(EventCode.MIRROR_BUILD_NO_BANDS.value, conn.events_emitted())

  def test_missing_conn_or_ids_skips_emit(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.mirror import (
      build_mirror,
    )
    # No emit when conn is None — should not raise.
    mirror = build_mirror(
      None, draft_id="d", planning_run_id="r",
      business_facts={}, plan_state={}, load_bands=False,
    )
    self.assertIsNotNone(mirror)


# ---------------------------------------------------------------------------
# Orchestrator finmo_sync source-shape regression check
# ---------------------------------------------------------------------------

class OrchestratorFinmoSyncShapeTest(unittest.TestCase):
  def test_initial_grid_runner_emits_finmo_sync_pair(self) -> None:
    """Confirm the orchestrator's baseline_finmo_sync invocation is
    bracketed by FINMO_SYNC_STARTED + FINMO_SYNC_COMPLETED emits."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "python"
           / "client_intake_and_finmo" / "post_intake_initial_grid"
           / "runner.py").read_text(encoding="utf-8")
    self.assertIn("FINMO_SYNC_STARTED", src)
    self.assertIn("FINMO_SYNC_COMPLETED", src)
    self.assertIn('"baseline_finmo_sync"', src)


if __name__ == "__main__":
  unittest.main()
