"""Acceptance tests for the SolverInputContract classmethod adapter
added in Contract 3 Commit 2.

Spec: ``docs/architecture/p3_40_contract_3_solver_input_spec.md`` §6
Commit 2. Per Flag 1 (classmethod-only, no SolverInputBundle
dataclass) the adapter consists of two classmethods on
``SolverInputContract``:

  - ``from_initial_grid_state(state, *, draft_id, planning_run_id=None)``
  - ``to_initial_grid_state()``
"""

from __future__ import annotations

import copy
import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from pydantic import ValidationError  # noqa: E402

from client_intake_and_finmo.post_intake_contracts.solver_input_contract import (  # noqa: E402
  SolverInputContract,
)
from _p3_40_contract_3_fixtures import (  # noqa: E402
  valid_solver_input_dict,
)


def _state_from_fixture(**fixture_kwargs) -> dict:
  """Build a dict in the shape ``prepare_initial_grid_for_draft``
  returns at runner.py:1830-1850. The fixture's
  ``valid_solver_input_dict`` already has the 19 data fields +
  planning_run_id at the top level; we add the 3 non-contract
  keys the runner attaches (`draft`, `post_intake_process_sequence_trace`,
  `shared_context`) plus an in-state ``planning_run_id`` so
  ``from_initial_grid_state`` exercises both the explicit-kwarg
  and the state-source paths."""
  payload = valid_solver_input_dict(**fixture_kwargs)
  # The runner emits planning_run_id at the top level of the dict;
  # the contract accepts it via either the state or the explicit
  # kwarg path.
  state = dict(payload)
  state["draft"] = {"draft_id": payload["draft_id"], "internal_db_column": "leak_me"}
  state["post_intake_process_sequence_trace"] = [{"stage": "init"}]
  state["shared_context"] = {"some_context_blob": "..."}
  return state


# ---------------------------------------------------------------------------
# from_initial_grid_state — happy path + non-contract key dropping
# ---------------------------------------------------------------------------

class FromInitialGridStateTest(unittest.TestCase):

  def test_returns_solver_input_contract(self) -> None:
    state = _state_from_fixture()
    contract = SolverInputContract.from_initial_grid_state(
      state, draft_id=state["draft_id"], planning_run_id=state["planning_run_id"]
    )
    self.assertIsInstance(contract, SolverInputContract)

  def test_drops_non_contract_keys_without_raising(self) -> None:
    """The runner emits `draft`, `post_intake_process_sequence_trace`,
    `shared_context` which the solver doesn't consume. The adapter
    drops them; if it didn't, extra='forbid' on top-level would
    reject the payload."""
    state = _state_from_fixture()
    contract = SolverInputContract.from_initial_grid_state(
      state, draft_id=state["draft_id"], planning_run_id=state["planning_run_id"]
    )
    self.assertFalse(hasattr(contract, "draft"))
    self.assertFalse(hasattr(contract, "post_intake_process_sequence_trace"))
    self.assertFalse(hasattr(contract, "shared_context"))

  def test_uses_explicit_kwarg_planning_run_id_when_provided(self) -> None:
    state = _state_from_fixture()
    state["planning_run_id"] = "run_in_state"
    contract = SolverInputContract.from_initial_grid_state(
      state, draft_id="draft_x", planning_run_id="run_via_kwarg"
    )
    self.assertEqual(contract.planning_run_id, "run_via_kwarg")
    self.assertEqual(contract.draft_id, "draft_x")

  def test_falls_back_to_state_planning_run_id_when_kwarg_is_None(self) -> None:
    state = _state_from_fixture()
    state["planning_run_id"] = "run_from_state"
    contract = SolverInputContract.from_initial_grid_state(
      state, draft_id="draft_x", planning_run_id=None
    )
    self.assertEqual(contract.planning_run_id, "run_from_state")

  def test_loads_all_19_data_fields(self) -> None:
    state = _state_from_fixture()
    contract = SolverInputContract.from_initial_grid_state(
      state, draft_id=state["draft_id"], planning_run_id=state["planning_run_id"]
    )
    self.assertEqual(contract.planning_mode, "rebalance")
    self.assertEqual(contract.business_facts.fact_template["business_stage"], "growth")
    self.assertIsNotNone(contract.applied_model_input_json)
    self.assertIsNotNone(contract.applied_finmo_json)
    self.assertIsNotNone(contract.stage_ramp_contract)
    self.assertIsNotNone(contract.payroll_headcount)


# ---------------------------------------------------------------------------
# from_initial_grid_state — rejection paths
# ---------------------------------------------------------------------------

class FromInitialGridStateRejectionTest(unittest.TestCase):

  def test_empty_planning_run_id_rejected(self) -> None:
    """Flag 8(a) tightening: empty string fails min_length=1."""
    state = _state_from_fixture()
    state["planning_run_id"] = ""
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.from_initial_grid_state(
        state, draft_id="draft_x", planning_run_id=""
      )
    self.assertIn("planning_run_id", str(ctx.exception))

  def test_bad_applied_model_input_json_rejected(self) -> None:
    """Contract 1 invariant violation propagates through adapter."""
    state = _state_from_fixture()
    state["applied_model_input_json"]["sections"]["revenue"] = []
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.from_initial_grid_state(
        state, draft_id=state["draft_id"], planning_run_id=state["planning_run_id"]
      )
    self.assertIn("revenue", str(ctx.exception))

  def test_missing_required_field_rejected(self) -> None:
    state = _state_from_fixture()
    del state["business_facts"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.from_initial_grid_state(
        state, draft_id=state["draft_id"], planning_run_id=state["planning_run_id"]
      )
    self.assertIn("business_facts", str(ctx.exception))


# ---------------------------------------------------------------------------
# Round-trip: state -> contract -> state preserves 19 data fields
# ---------------------------------------------------------------------------

class RoundTripTest(unittest.TestCase):

  def test_round_trip_preserves_data_fields(self) -> None:
    state = _state_from_fixture()
    contract = SolverInputContract.from_initial_grid_state(
      state, draft_id=state["draft_id"], planning_run_id=state["planning_run_id"]
    )
    round_tripped = contract.to_initial_grid_state()
    # 19 data fields + draft_id + planning_run_id are preserved.
    # Non-contract keys (draft / sequence trace / shared_context)
    # are dropped by design.
    for key in (
      "draft_id", "planning_run_id", "business_facts", "ops_json",
      "financials_json", "financials_year1_json",
      "applied_model_input_json", "applied_finmo_json",
      "planning_mode", "planning_mode_reason", "people_json",
      "fulfillment_json", "marketing_model_json",
      "target_market_json", "planning_result",
      "catalog_source_model_input_json", "stage_ramp_contract",
      "payroll_headcount", "planning_context_summary_json",
      "grid_application_summary",
    ):
      self.assertIn(key, round_tripped, f"missing {key} after round-trip")
    self.assertNotIn("draft", round_tripped)
    self.assertNotIn("post_intake_process_sequence_trace", round_tripped)
    self.assertNotIn("shared_context", round_tripped)

  def test_round_trip_preserves_planning_mode_value(self) -> None:
    """Spot-check a Literal-typed value survives round-trip."""
    state = _state_from_fixture()
    state["planning_mode"] = "turnaround"
    contract = SolverInputContract.from_initial_grid_state(
      state, draft_id=state["draft_id"], planning_run_id=state["planning_run_id"]
    )
    round_tripped = contract.to_initial_grid_state()
    self.assertEqual(round_tripped["planning_mode"], "turnaround")


if __name__ == "__main__":
  unittest.main()
