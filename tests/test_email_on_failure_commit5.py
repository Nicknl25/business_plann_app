"""Phase 9 P3.10 Commit 5 — smoke tests for the email-on-failure
feature and the Phase-3 floor audit's log escalation.

Verifies:
  - send_failure_alert composes the correct subject and unpacked
    diagnostic body; returns a status dict; never raises.
  - send_failure_alert with missing env vars logs at ERROR and
    returns sent=False with reason=missing_env_vars.
  - build_run_failure_email_body unpacks structured diagnostic
    (operation, pipeline_stage, expected, actual, details, cause)
    when present.
  - The cash strategy review WARNING-level critic failure logs were
    escalated to ERROR (Commit 5 Part A outcome).
"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest import mock


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class EmailOnFailureCommit5Test(unittest.TestCase):
  def setUp(self) -> None:
    self._env_backup = {}
    for k in (
      "EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_HOST",
      "EMAIL_PORT", "EMAIL_ALERTS_ADDRESS",
    ):
      self._env_backup[k] = os.environ.get(k)

  def tearDown(self) -> None:
    for k, v in self._env_backup.items():
      if v is None:
        os.environ.pop(k, None)
      else:
        os.environ[k] = v

  def test_failure_body_unpacks_structured_diagnostic(self) -> None:
    from client_intake_and_finmo.workbook_email import (  # noqa: WPS433
      build_run_failure_email_body,
    )
    body = build_run_failure_email_body(
      business_name="NexGen Software Solutions Inc.",
      exception_class="PostIntakePreconditionFailed",
      exception_message="post_intake_precondition_failed: operation=foo",
      failure_diagnostic={
        "operation": "foo_operation",
        "pipeline_stage": "stage_X",
        "expected": "good thing",
        "actual": "bad thing",
        "details": {"k1": "v1", "k2": "v2"},
        "cause_class": "RuntimeError",
        "cause_detail": "underlying cause string",
      },
      draft_id="abc123",
      planning_run_id="run456",
    )
    self.assertIn("NexGen Software Solutions Inc.", body)
    self.assertIn("PostIntakePreconditionFailed", body)
    self.assertIn("foo_operation", body)
    self.assertIn("stage_X", body)
    self.assertIn("good thing", body)
    self.assertIn("bad thing", body)
    self.assertIn("k1: v1", body)
    self.assertIn("k2: v2", body)
    self.assertIn("RuntimeError", body)
    self.assertIn("underlying cause string", body)
    self.assertIn("abc123", body)
    self.assertIn("run456", body)
    self.assertIn("Captured by Phase 9 P3.10 Commit 5 Part B", body)

  def test_failure_body_handles_missing_diagnostic(self) -> None:
    from client_intake_and_finmo.workbook_email import (  # noqa: WPS433
      build_run_failure_email_body,
    )
    body = build_run_failure_email_body(
      business_name="Sunny Glaze Donuts",
      exception_class="RuntimeError",
      exception_message="something went wrong",
      failure_diagnostic=None,
      draft_id="d1",
      planning_run_id=None,
    )
    self.assertIn("Sunny Glaze Donuts", body)
    self.assertIn("something went wrong", body)
    # Diagnostic-section keys must NOT appear when failure_diagnostic is empty.
    self.assertNotIn("Structured diagnostic:", body)

  def test_send_failure_alert_missing_env_returns_status_dict(self) -> None:
    from client_intake_and_finmo.workbook_email import (  # noqa: WPS433
      send_failure_alert,
    )
    # Strip all env vars so the helper short-circuits.
    for k in (
      "EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_HOST",
      "EMAIL_PORT", "EMAIL_ALERTS_ADDRESS",
    ):
      os.environ.pop(k, None)

    with self.assertLogs(
      "client_intake_and_finmo.workbook_email",
      level=logging.ERROR,
    ) as cm:
      result = send_failure_alert(
        business_name="Test Co.",
        exception_class="RuntimeError",
        exception_message="boom",
        failure_diagnostic={"operation": "op_a"},
        draft_id="d1",
        planning_run_id="r1",
      )
    self.assertFalse(result["sent"])
    self.assertEqual(result["reason"], "missing_env_vars")
    self.assertIn("EMAIL_USER", result["missing"])
    self.assertEqual(
      result["subject"],
      "POST-INTAKE FAILURE: Test Co. - RuntimeError",
    )
    self.assertTrue(
      any("workbook_failure_email_missing_env_vars" in m for m in cm.output),
      f"expected ERROR log not found in {cm.output}",
    )

  def test_send_failure_alert_smtp_failure_logged_at_error(self) -> None:
    from client_intake_and_finmo.workbook_email import (  # noqa: WPS433
      send_failure_alert,
    )
    os.environ["EMAIL_USER"] = "test@example.com"
    os.environ["EMAIL_PASSWORD"] = "pass"
    os.environ["EMAIL_HOST"] = "smtp.example.com"
    os.environ["EMAIL_PORT"] = "587"
    os.environ["EMAIL_ALERTS_ADDRESS"] = "alerts@example.com"

    with mock.patch(
      "client_intake_and_finmo.workbook_email.smtplib.SMTP",
      side_effect=Exception("simulated SMTP failure"),
    ):
      with self.assertLogs(
        "client_intake_and_finmo.workbook_email",
        level=logging.ERROR,
      ) as cm:
        result = send_failure_alert(
          business_name="Failing Co.",
          exception_class="PostIntakePreconditionFailed",
          exception_message="something broke",
          failure_diagnostic={"operation": "op_x"},
          draft_id="d2",
          planning_run_id="r2",
        )
    self.assertFalse(result["sent"])
    self.assertEqual(result["reason"], "smtp_failed")
    self.assertIn("Failing Co.", result["subject"])
    self.assertTrue(
      any("workbook_failure_email_send_failed" in m for m in cm.output),
      f"expected SMTP ERROR log not found in {cm.output}",
    )

  def test_cash_strategy_critic_logs_escalated_to_error(self) -> None:
    """Commit 5 Part A — three cash_strategy_review_critic failure
    paths log at ERROR (was WARNING). Source-level verification."""
    import pathlib

    cash_path = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_cash"
      / "runner.py"
    )
    text = cash_path.read_text(encoding="utf-8")
    # Each of the three critic-failure log sites must be ERROR-level
    # and reference the Commit 5 Part A floor verification.
    self.assertIn(
      'logger.error(\n        "cash_strategy_review_critic_http_error: status=%s body=%s; "',
      text,
    )
    self.assertIn(
      'logger.error(\n          "cash_strategy_review_critic_invalid_payload: %s; "',
      text,
    )
    self.assertIn(
      'logger.error(\n      "cash_strategy_review_critic_unexpected_error: %s; "',
      text,
    )
    # The Phase 9 P3.10 Commit 5 Part A marker must be present so the
    # provenance is auditable.
    self.assertIn(
      "Phase 9 P3.10 Commit 5 Part A",
      text,
    )

  def test_dispatch_helper_present_in_intake_consult(self) -> None:
    """The Commit 5 Part B dispatch helper must be defined and exposed."""
    import api_handlers.intake_consult as m  # noqa: WPS433
    self.assertTrue(hasattr(m, "_dispatch_post_intake_failure_alert"))


if __name__ == "__main__":
  unittest.main()
