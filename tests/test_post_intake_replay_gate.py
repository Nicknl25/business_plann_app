"""The post-intake replay gate's own judgment (2026-09-11).

The gate decides whether a post-intake change ships, so its verdict logic is
pinned on the real failure texts it has to classify: Ferriday & Blythe's
09-11 payload-build failure (d44f717c) and Bramblewood's 09-10 people-shape
failure (a9db48dd).
"""
from __future__ import annotations

import datetime
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location(
  "replay_post_intake", os.path.join(ROOT, "scripts", "replay_post_intake.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

VET_D44F717C = (
  "post_intake_fail_fast::fail_round1_set_tool_rejected: set_payroll_schedule(contract=None) "
  "rejected: violations=[{'code': 'payroll_payload_build_failed', 'message': "
  "'POST_INTAKE:payroll_headcount_schedule_validation_failed@payroll_headcount_payload_build: "
  "payroll_headcount_unapproved_text_field:payroll_headcount.stated_payroll_reconciliation."
  "stated_source'}]")
SUNNY_C8A6B6B5_STOP = (
  "post_intake_fail_fast::fail_round1_set_tool_rejected: set_payroll_schedule(contract=None) "
  "rejected: violations=[{'code': 'payroll_payload_build_failed', 'message': \"POST_INTAKE:"
  "payroll_authored_off_stated_payroll@payroll_headcount_payload_build: the authored Q1 roster "
  "annualizes to $112,370 against the operator's STATED payroll of $183,322 (ratio 0.61, band "
  "0.7-1.3).")
BRAMBLEWOOD_A9DB48DD = (
  "INTAKE->POST_INTAKE: field 'people_json.people.4.full_name' expected Field required "
  "(and 55 more error(s)), got {'name': 'Dr. Ingrid Solvang'")


class SignatureTests(unittest.TestCase):
  def test_the_vet_signature_is_the_innermost_cause_with_its_field(self):
    self.assertEqual(
      R.signature(VET_D44F717C),
      "payroll_headcount_unapproved_text_field:"
      "payroll_headcount.stated_payroll_reconciliation.stated_source")

  def test_the_shared_wrapper_is_never_the_signature(self):
    self.assertNotIn("post_intake_fail_fast", R.signature(VET_D44F717C))
    self.assertNotIn("fail_round1", R.signature(VET_D44F717C))

  def test_a_different_field_is_a_different_signature(self):
    other = VET_D44F717C.replace("stated_source", "created_wage_basis")
    self.assertNotEqual(R.signature(other), R.signature(VET_D44F717C))

  def test_the_reconciliation_stop_signs_as_its_code_not_its_location(self):
    """The recording pass (2026-09-11) read the location token and called
    Sunny Glaze a REGRESSION instead of a new rule meeting an old draft."""
    self.assertEqual(R.signature(SUNNY_C8A6B6B5_STOP), "payroll_authored_off_stated_payroll")

  def test_the_replay_and_a_real_run_sign_the_same_failure_alike(self):
    """The worker stores str(exc), exactly as planning_runs.failure_reason."""
    self.assertEqual(R.signature(BRAMBLEWOOD_A9DB48DD),
                     R.signature(BRAMBLEWOOD_A9DB48DD + " (more text)"))

  def test_a_failure_with_no_code_is_still_signed_stably(self):
    self.assertEqual(R.signature(BRAMBLEWOOD_A9DB48DD), R.signature(BRAMBLEWOOD_A9DB48DD))
    self.assertTrue(R.signature(BRAMBLEWOOD_A9DB48DD))


class JudgeTests(unittest.TestCase):
  SRC_OK = {"draft_id": "a", "status": "completed", "signature": None}
  SRC_BAD = {"draft_id": "b", "status": "failed", "signature": R.signature(VET_D44F717C)}
  DONE = {"outcome": "completed"}
  SAME = {"outcome": "failed", "detail": VET_D44F717C}
  OTHER = {"outcome": "failed",
           "detail": VET_D44F717C.replace("stated_source", "created_wage_basis")}

  def test_truth_table(self):
    cases = [
      (self.SRC_OK, self.DONE, {}, "PASS"),
      (self.SRC_BAD, self.DONE, {}, "FIXED"),
      (self.SRC_OK, self.SAME, {}, "REGRESSION"),
      (self.SRC_BAD, self.SAME, {}, "KNOWN"),
      (self.SRC_BAD, self.OTHER, {}, "NEW_FAILURE"),
      (self.SRC_OK, dict(self.DONE, gpt_miss_count=1), {}, "GPT_MISS"),
      (self.SRC_OK, {"verdict_raw": "ERROR", "outcome": "failed"}, {}, "ERROR"),
      (self.SRC_OK, self.SAME, {"a": {"signature": R.signature(VET_D44F717C)}}, "BLESSED"),
      (self.SRC_OK, self.OTHER, {"a": {"signature": R.signature(VET_D44F717C)}}, "REGRESSION"),
    ]
    for src, rep, blessed, want in cases:
      self.assertEqual(R.judge(src, rep, blessed), want, (src, rep, blessed))

  def test_a_gpt_miss_is_never_a_pass(self):
    """A swallowed miss can leave the pipeline 'completing' on another path."""
    self.assertEqual(R.judge(self.SRC_OK, dict(self.DONE, gpt_miss_count=2), {}), "GPT_MISS")

  def test_what_blocks_a_ship(self):
    self.assertEqual(set(R.BLOCKING), {"REGRESSION", "NEW_FAILURE", "GPT_MISS", "ERROR",
                                       "ACCEPTANCE_DROP"})


class AcceptanceTests(unittest.TestCase):
  RAN = datetime.datetime(2026, 9, 10, 17, 27)
  SRC = {"draft_id": "h", "status": "completed", "signature": None,
         "run_started": RAN, "acceptance_passed": True}

  def _rep(self, passed, checks=()):
    return {"outcome": "completed", "acceptance_passed": passed,
            "acceptance_failed_checks": list(checks)}

  def test_a_plan_that_stops_passing_acceptance_blocks(self):
    older = lambda code: datetime.datetime(2026, 8, 1)
    self.assertEqual(R.judge(self.SRC, self._rep(False, ["payroll_ratio_in_band"]), {}, older),
                     "ACCEPTANCE_DROP")

  def test_a_newer_acceptance_check_does_not_block(self):
    newer = lambda code: datetime.datetime(2026, 9, 11, 9, 0)
    self.assertEqual(R.judge(self.SRC, self._rep(False, ["payroll_ratio_in_band"]), {}, newer),
                     "POSTDATES")

  def test_a_drop_with_no_named_check_never_excuses_itself(self):
    newer = lambda code: datetime.datetime(2026, 9, 11, 9, 0)
    self.assertEqual(R.judge(self.SRC, self._rep(False), {}, newer), "ACCEPTANCE_DROP")

  def test_a_blessed_drop_matches_only_its_exact_check_set(self):
    blessed = {"h": {"acceptance_failed_checks": ["viability_timeline_landed",
                                                  "realism_gate_no_hard_fail_violations"]}}
    older = lambda code: datetime.datetime(2026, 8, 1)
    same = self._rep(False, ["realism_gate_no_hard_fail_violations", "viability_timeline_landed"])
    more = self._rep(False, ["realism_gate_no_hard_fail_violations", "viability_timeline_landed",
                             "cash_never_negative"])
    self.assertEqual(R.judge(self.SRC, same, blessed, older), "BLESSED")
    self.assertEqual(R.judge(self.SRC, more, blessed, older), "ACCEPTANCE_DROP")

  def test_still_passing_or_never_passed_is_not_a_drop(self):
    self.assertEqual(R.judge(self.SRC, self._rep(True), {}), "PASS")
    self.assertEqual(R.judge(dict(self.SRC, acceptance_passed=False), self._rep(False), {}), "PASS")
    self.assertEqual(R.judge(dict(self.SRC, acceptance_passed=None), self._rep(False), {}), "PASS")

  def test_stored_verdicts_are_read_honestly(self):
    self.assertIs(R._acceptance_passed('{"passed": true}'), True)
    self.assertIs(R._acceptance_passed('{"passed": false}'), False)
    self.assertIsNone(R._acceptance_passed(None))
    self.assertIsNone(R._acceptance_passed("not json"))


class PostdatesTests(unittest.TestCase):
  """Nick 2026-09-11: 'fails a check that postdates its original run doesn't
  block.' Sunny Glaze and Bramblewood ran before the reconciliation existed."""
  RAN = datetime.datetime(2026, 9, 9, 13, 3)
  SRC = {"draft_id": "s", "status": "completed", "signature": None, "run_started": RAN}
  STOP = {"outcome": "failed", "detail": VET_D44F717C}

  def test_a_check_newer_than_the_run_does_not_block(self):
    newer = lambda code: datetime.datetime(2026, 9, 10, 18, 31)
    self.assertEqual(R.judge(self.SRC, self.STOP, {}, newer), "POSTDATES")
    self.assertNotIn("POSTDATES", R.BLOCKING)

  def test_a_check_older_than_the_run_still_blocks(self):
    older = lambda code: datetime.datetime(2026, 8, 1)
    self.assertEqual(R.judge(self.SRC, self.STOP, {}, older), "REGRESSION")

  def test_an_unknown_introduction_never_excuses(self):
    self.assertEqual(R.judge(self.SRC, self.STOP, {}, lambda code: None), "REGRESSION")
    self.assertEqual(R.judge(dict(self.SRC, run_started=None), self.STOP, {},
                             lambda code: datetime.datetime(2026, 9, 10)), "REGRESSION")

  def test_the_new_stamp_failing_an_old_check_is_a_regression(self):
    """The vet failure class: today's stamp against a validator code that
    predates every draft - exactly what must block."""
    when = R.check_introduced("payroll_headcount_unapproved_text_field")
    self.assertIsNotNone(when)
    self.assertLess(when, self.RAN)

  def test_the_reconciliation_stop_postdates_the_sunny_runs(self):
    when = R.check_introduced("payroll_authored_off_stated_payroll")
    self.assertIsNotNone(when)
    self.assertGreater(when, datetime.datetime(2026, 9, 10, 17, 0))


class ScratchPolicyTests(unittest.TestCase):
  def test_every_post_intake_output_is_reset_on_the_clone(self):
    for col in ("model_input_json", "finmo_json", "payroll_headcount", "debt_schedule",
                "marketing_schedule_json", "numeric_solver_feedback_json"):
      self.assertIn(col, R.RESET_COLUMNS)

  def test_the_response_store_is_never_swept(self):
    self.assertIn("post_intake_gpt_response_store", R.NEVER_SWEEP)

  def test_workers_cannot_mail_or_deliver(self):
    for key in ("EMAIL_HOST", "EMAIL_ALERTS_ADDRESS", "FINMO_MODEL_DELIVERY_DIR"):
      self.assertIn(key, R.EMAIL_KEYS)


if __name__ == "__main__":
  unittest.main()
