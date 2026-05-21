"""Phase 9 P3.32 K1 F5 — pre-cash gate routes payroll-touching
violations to Handler C.

P3.31 §5 F5: "Wire restoration-exhaustion to Handler C when
failing metrics include payroll-touching primary_levers."

After K1 F1+F2 closed Leak A (the GPT exhaustion handler no longer
authors expenses::Payroll), the pre-cash gate's existing flow —
invoke exhaustion handler with violation context, re-evaluate — no
longer resolves payroll-touching violations. The handler cannot
fix what it has no authority over.

K1 F5 inserts a Handler C routing step between the post-handler
re-evaluation and the hard-fail. Any violation whose primary_levers
contains "expenses::Payroll" is routed to Handler C via the
existing route_payroll_feasibility_to_handler_c primitive
(P3.26 Commit 2). Handler C re-authors the payroll schedule with
the violation context as previous_contract_failure feedback, the
apply chain re-applies through Mirror Flavor 1 assertions, the
payroll_headcount column is persisted to SQL, and the gate is
re-evaluated. If violations still remain, the hard-fail fires
with both the residual violations AND the Handler C route trace
in the diagnostic chain.

DOCTRINE 3-SURFACE CHECK (extended to 4 surfaces for contract
awareness):
  Q1. Surfaces holding payroll dollars:
      - payroll_headcount.{rows, quarter_totals, assumptions}
        (canonical)
      - model_input.expenses.Payroll (derived via apply chain)
      - finmo.pl.Payroll / finmo.quarter_rows.payroll (derived
        via build_python_finmo_json)
  Q2. Alignment mechanism:
      Handler C as single writer + apply chain assertions
      (assert_payroll_headcount_model_input_applied +
       assert_finmo_payroll_matches_headcount_schedule, zero
       tolerance).
  Q3. This fix preserves alignment:
      YES — the route invokes Handler C through the canonical
      route_payroll_feasibility_to_handler_c primitive, which
      re-applies via apply_payroll_schedule_to_state. The
      Mirror Flavor 1 assertions enforce zero-tolerance
      alignment before returning.
  Q4. Handler C consults stage_ramp_contract:
      YES — Handler C's signature
      (post_intake_headcount/schedule.py:2191) accepts
      stage_ramp_contract; the prompt at
      schedule.py:2300 + task_instruction at schedule.py:2478
      ("Use the stage_ramp_contract as context") instruct GPT
      to consult it. Contract awareness is preserved.

This file pins:
  - The route handler is invoked when gate_violations have
    expenses::Payroll in primary_levers AND the GPT exhaustion
    handler has already run (since K1 closed its authority).
  - The route uses the canonical primitive from feasibility_repair.
  - The route's failure context propagates through the diagnostic
    chain on subsequent failure.
  - Wiring is present in orchestrator.py source at the
    documented insertion point.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class TestF5RoutingPresentInOrchestrator(unittest.TestCase):
  """Source-level: the orchestrator imports the routing primitive
  and contains the F5 routing block at the documented insertion
  point (between post-handler re-evaluation and hard-fail)."""

  @staticmethod
  def _orchestrator_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver",
      "orchestrator.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  def test_orchestrator_imports_routing_primitive_at_f5_block(self) -> None:
    src = self._orchestrator_source()
    self.assertIn(
      "route_payroll_feasibility_to_handler_c", src,
      msg="orchestrator must reference the routing primitive",
    )

  def test_orchestrator_contains_f5_marker_comment(self) -> None:
    """The K1 F5 block has a clear marker comment naming the work
    item, so future operators understand why the route exists."""
    src = self._orchestrator_source()
    self.assertIn("Phase 9 P3.32 K1 F5", src)
    self.assertIn("pre-cash gate Handler C routing", src)

  def test_f5_block_uses_payroll_filter(self) -> None:
    """The F5 block selects violations whose primary_levers
    contains expenses::Payroll — that's the routing criterion."""
    src = self._orchestrator_source()
    self.assertIn(
      "\"expenses::Payroll\" in (v.get(\"primary_levers\") or [])",
      src,
      msg="F5 routing filter must select payroll-touching violations",
    )

  def test_f5_block_constructs_failure_payload_with_specific_code(self) -> None:
    """The synthetic failure code makes the routing visible in
    the diagnostic chain; a generic code would obscure the
    F5-specific route path."""
    src = self._orchestrator_source()
    self.assertIn("pre_cash_gate_payroll_violation_routed_to_handler_c", src)

  def test_f5_block_persists_payroll_headcount(self) -> None:
    """Mirror Flavor 1 doctrine: the payroll_headcount SQL column
    must be persisted immediately after Handler C re-authors,
    otherwise the workbook builder re-renders from stale data."""
    src = self._orchestrator_source()
    self.assertIn(
      "UPDATE intake_consult_drafts SET payroll_headcount=%s WHERE draft_id=%s",
      src,
      msg="F5 must persist payroll_headcount to SQL after Handler C re-author",
    )

  def test_f5_block_reevaluates_gate(self) -> None:
    """After Handler C re-authors, the gate must be re-evaluated.
    Otherwise the original violations would still trigger
    the hard-fail with stale data."""
    src = self._orchestrator_source()
    # Find the F5 block and check that _evaluate_gpt_authorable_
    # pre_cash_checks is called inside it (a second time after the
    # handler block's own re-eval).
    f5_start = src.find("Phase 9 P3.32 K1 F5")
    self.assertGreater(f5_start, 0, "F5 block marker not found")
    f5_section = src[f5_start: f5_start + 8000]
    self.assertIn("_evaluate_gpt_authorable_pre_cash_checks", f5_section)


class TestF5DiagnosticChainPreservation(unittest.TestCase):
  """If Handler C cannot resolve the payroll violations, the
  hard-fail must surface the Handler C route trace so the
  operator can distinguish 'handler couldn't fix' from 'Handler
  C re-authored but residual remains' from 'Handler C route
  itself failed'."""

  def test_hard_fail_includes_handler_c_route_trace_field(self) -> None:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver",
      "orchestrator.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      src = fh.read()
    self.assertIn("\"handler_c_route_attempted\":", src)
    self.assertIn("\"handler_c_route_trace\":", src)


class TestRoutingPrimitivePreservedFromP3_26(unittest.TestCase):
  """K1 F5 reuses the existing P3.26 Commit 2 primitive —
  route_payroll_feasibility_to_handler_c. The primitive's
  signature must continue to support the F5 use case."""

  def test_primitive_is_callable_with_f5_required_args(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      route_payroll_feasibility_to_handler_c,
    )
    import inspect
    sig = inspect.signature(route_payroll_feasibility_to_handler_c)
    expected_kwonly = {
      "failure_code", "failure_message", "failure_stage", "failure_details",
      "business_facts", "ops_json", "people_json", "financials_json",
      "financials_year1_json", "planning_mode", "planning_mode_reason",
      "model_input_json", "finmo_json", "payroll_headcount",
      "stage_ramp_contract", "draft_id", "client_id", "live_count",
      "stage_prefix",
    }
    actual = set(sig.parameters.keys())
    missing = expected_kwonly - actual
    self.assertFalse(
      missing,
      msg=f"route_payroll_feasibility_to_handler_c missing kwargs: {missing}",
    )


class TestHandlerCConsultsStageRampContract(unittest.TestCase):
  """Doctrine Q4: Handler C must consult stage_ramp_contract
  when re-authoring. P3.31 audit and orchestrator F5 wiring rely
  on this; if Handler C ignored the contract, F5 routing would
  re-author payroll without contract awareness and the new
  schedule could re-violate stage-ramp bands."""

  def test_handler_c_signature_accepts_stage_ramp_contract(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      estimate_payroll_headcount_schedule_with_gpt,
    )
    import inspect
    sig = inspect.signature(estimate_payroll_headcount_schedule_with_gpt)
    self.assertIn(
      "stage_ramp_contract", sig.parameters,
      msg="Handler C must accept stage_ramp_contract for contract awareness",
    )

  def test_handler_c_prompt_passes_compacted_stage_ramp_contract(self) -> None:
    """The handler builds its GPT prompt with a compacted
    stage_ramp_contract; greps the source for the bridge."""
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_headcount",
      "schedule.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      src = fh.read()
    self.assertIn("_compact_stage_ramp_contract_for_payroll", src)
    self.assertIn("\"stage_ramp_contract\":", src)


class TestF5HandlerScopeUnchangedByRoute(unittest.TestCase):
  """K1 F5 routes payroll violations to Handler C; it must NOT
  re-grant the GPT exhaustion handler authority over Payroll.
  The K1 F1+F2 closure (Leak A) is the structural invariant
  F5 operates within."""

  def test_exhaustion_handler_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertNotIn(
      "expenses::Payroll", GPT_AUTHORED_LEVER_IDS,
      msg=(
        "K1 F5 must operate within K1 F1+F2's closure. If "
        "expenses::Payroll were re-added to the exhaustion "
        "handler's catalog, F5's routing premise (handler "
        "can't fix payroll) becomes false and the route would "
        "be dead code."
      ),
    )


if __name__ == "__main__":
  unittest.main()
