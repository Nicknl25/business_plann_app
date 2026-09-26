"""A RUN DOES NOT REPORT A VERDICT IT NEVER REACHED (2026-09-26).

Nick's step-4 criterion is "convergence_cycle_count > 0 and
hard_rules_cleared true". The Pellingham run (draft 2994f04b, run b4f451ed)
came back completed, with acceptance passed on every check, plan_confidence
high_no_adaptation and cascade_landed_tier 0 - and reported:

    current_cycle 0, hard_rule_state {}, all_hard_rules_cleared False,
    overall_completion_score_pct 0, grade D

Two separate wrongs in one report:

  * all_hard_rules_cleared was False because NOTHING WAS ASSESSED. The
    assessor is a pure function of the controller state and the final finmo
    (the accounting identity every quarter, plus any blocking issue still
    open) and it has existed all along - the finalize persist just never
    called it, and convergence_state_json.hard_rule_state is read from
    unified_convergence_context["hard_rule_assessment"]. Same shape as the
    all_cleared defect: a conclusion drawn from an absence.

  * the cycle count was a HARDCODED 0, next to a hardcoded empty decision,
    plan, result and iterations list. Zero can be the true number - a plan
    the cascade never had to touch - but only if the run says which it is.
    That is what run_outcome.no_adaptation_needed is for.
"""
import ast
import inspect
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from client_intake_and_finmo.post_intake_solver import orchestrator as O  # noqa: E402
from client_intake_and_finmo.post_intake_convergence import runtime as CR  # noqa: E402

# THE RUNTIME IS INJECTED, so a test that calls into it has to wire it the
# way the API does (api_handlers.intake_consult._bind_post_intake_runtime_
# dependencies) - otherwise the helpers the assessor leans on are undefined
# and the test reports a NameError as if it were a product failure.
def _bind_the_runtime():
  from api_handlers import intake_consult as _ic  # noqa: F401
  _ic._bind_post_intake_runtime_dependencies()


SRC = io.open(
  os.path.join(os.path.dirname(__file__), "..", "python", "client_intake_and_finmo",
               "post_intake_solver", "orchestrator.py"), encoding="utf-8").read()


def _finmo(*, gap=0.0, quarters=20):
  """A finmo whose rows are GENUINELY (un)balanced.

  The metrics the assessor reads are recomputed from the row's own asset and
  liability fields by an injected helper - a fabricated
  accounting_equation_check is ignored, so a fixture that only sets that
  field tests nothing (this test did, on its first pass).
  """
  rows = []
  for q in range(1, quarters + 1):
    rows.append({
      "quarter_index": q,
      "year": 1 + (q - 1) // 4,
      "quarter": ((q - 1) % 4) + 1,
      "date": "2026-%02d-01" % (((q - 1) % 4) * 3 + 1),
      "cash": 120_000.0,
      "accounts_receivable": 80_000.0,
      "inventory": 60_000.0,
      "prepaid_expenses": 0.0,
      "ppe": 740_000.0 + gap,          # the imbalance lives here
      "accumulated_depreciation": 0.0,
      "right_of_use_asset": 0.0,
      "accounts_payable": 90_000.0,
      "deferred_revenue": 0.0,
      "short_term_debt": 0.0,
      "long_term_debt": 310_000.0,
      "capital_lease_obligation": 0.0,
      "owners_capital": 220_000.0,
      "retained_earnings": 380_000.0,
      "other_equity": 0.0,
      "total_assets": 1_000_000.0 + gap,
      "total_liabilities": 400_000.0,
      "total_equity": 600_000.0,
      # total_liabilities_and_equity is what the metrics rows actually carry,
      # and it does NOT move with the imbalance - that is the gap.
      "total_liabilities_and_equity": 1_000_000.0,
      "ending_cash": 120_000.0,
      "beginning_cash": 120_000.0,
      "revenue": 600_000.0,
      "ebitda": 90_000.0,
      "net_income": 40_000.0,
    })
  return {"quarter_rows": rows}


class TheHardRulesAreAssessed(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    _bind_the_runtime()

  def test_the_context_carries_the_assessment_to_the_state(self):
    """convergence_state_json.hard_rule_state reads
    context["hard_rule_assessment"] - so the builder has to put it there."""
    context = O._build_minimal_convergence_context(
      stage_ramp_contract={"rows": [1]},
      adaptive_policy_dict={},
      planning_context_summary_json={},
      hard_rule_assessment={"all_hard_rules_cleared": True,
                            "contract_version": "unified_hard_rule_assessment_v1"},
      run_outcome={"no_adaptation_needed": True},
    )
    self.assertTrue(context["hard_rule_assessment"]["all_hard_rules_cleared"])
    self.assertTrue(context["run_outcome"]["no_adaptation_needed"])

  def test_an_absent_assessment_is_not_invented(self):
    context = O._build_minimal_convergence_context(
      stage_ramp_contract=None, adaptive_policy_dict=None,
      planning_context_summary_json=None)
    self.assertNotIn("hard_rule_assessment", context)
    self.assertNotIn("run_outcome", context)

  def test_the_state_builder_reads_it_back_as_the_hard_rule_state(self):
    """The two halves have to agree on the key, or this whole fix is a
    dictionary nobody opens."""
    packet = CR._build_current_cycle_convergence_packet(
      stage="post_intake_finalize_validation_completed",
      status="completed",
      planning_mode="rebalance",
      planning_mode_reason="",
      planning_context_summary={},
      unified_convergence_context={
        "hard_rule_assessment": {"all_hard_rules_cleared": True,
                                 "remaining_hard_issue_count": 0},
      },
      controller_resolution_state={"status": "all_cleared",
                                   "remaining_issue_count": 0},
      unified_convergence_cycle_count=0,
    )
    self.assertTrue(packet["hard_rule_state"]["all_hard_rules_cleared"])

  def test_a_clean_finmo_clears_and_a_broken_one_does_not(self):
    """The assessor itself, on the surface the finalize persist hands it."""
    cleared = CR._build_unified_hard_rule_assessment(
      controller_resolution_state={"status": "all_cleared"},
      current_finmo_json=_finmo(gap=0.0))
    self.assertTrue(cleared["all_hard_rules_cleared"])
    self.assertEqual([], cleared["accounting_failure_quarters"])
    broken = CR._build_unified_hard_rule_assessment(
      controller_resolution_state={"status": "all_cleared"},
      current_finmo_json=_finmo(gap=25_000.0))
    self.assertFalse(broken["all_hard_rules_cleared"])
    self.assertIn("accounting_integrity_failure", broken["failed_rule_codes"])


class TheCycleCountIsTheTrueNumber(unittest.TestCase):

  def test_the_hardcoded_zero_is_gone(self):
    """`unified_convergence_cycle_count=0` at the finalize persist, beside a
    hardcoded empty decision, plan, result and iterations - that is what made
    every run report nothing."""
    self.assertNotIn("unified_convergence_cycle_count=0,", SRC)
    self.assertIn("unified_convergence_cycle_count=_finalize_cycles,", SRC)

  def test_the_persist_no_longer_hands_over_empty_result_and_iterations(self):
    call = SRC.index("_persist_unified_convergence_state(\n      conn=conn,")
    block = SRC[call:SRC.index("completion_trace[\"persist_finalize_stage\"]", call)]
    self.assertNotIn("unified_convergence_result={},", block)
    self.assertNotIn("unified_convergence_iterations=[],", block)
    self.assertIn("hard_rule_assessment", block)
    self.assertIn("run_outcome", block)

  def test_zero_cycles_is_reported_as_an_outcome_not_a_silence(self):
    """A plan the cascade never had to touch, said out loud."""
    tree = ast.parse(SRC)
    text = SRC[SRC.index("_finalize_outcome = {"):]
    text = text[:text.index("}\n")]
    self.assertIn("no_adaptation_needed", text)
    self.assertIn("hard_rules_assessed", text)
    self.assertIn("cascade_tier_landed", text)
    self.assertTrue(tree)

  def test_the_assessment_failing_cannot_take_the_run_with_it(self):
    """Reporting is bookkeeping: the plan has already been built, and a
    failure here must not undo it."""
    block = SRC[SRC.index("_finalize_hard_rules: Dict[str, Any] = {}"):]
    block = block[:block.index("_finalize_tier = None")]
    self.assertIn("try:", block)
    self.assertIn("except Exception:", block)
    self.assertIn("FINALIZE_HARD_RULE_ASSESSMENT_FAILED", block)

  def test_the_orchestrator_has_a_logger_to_log_with(self):
    """The trace line would have raised NameError - there was no logger in
    this module at all."""
    self.assertTrue(hasattr(O, "logger"))
    self.assertIn("FINALIZE_RUN_OUTCOME", SRC)


if __name__ == "__main__":
  unittest.main()
