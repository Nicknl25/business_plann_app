"""P3.41 intake-remediation gate-circumvention tests.

Verifies that the flag-gated bypass in
``api_handlers/financials.py`` and
``client_intake_and_finmo/intake_submit_service.py`` skips the
two known-broken summary-gate checks
(``target_market_summary`` and ``key_people_summary``) when
``_SKIP_INTAKE_REMEDIATION_GATES = True`` and re-instates them
when the flag is flipped to ``False``.

The bypassed gates read fields that are intentionally popped
before persistence per commit e57ff49 (single-source-of-truth
enforcement) -- see commit 8a98e26 / Contract 5d R-d /
Contract 5c R-d-bis. The bypass is a TEMPORARY workaround so
E2E can flow through to post-intake; the proper fix lives in
the intake-remediation workstream.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


from client_intake_and_finmo import intake_submit_service  # noqa: E402
from client_intake_and_finmo.intake_submit_service import (  # noqa: E402
  IntakeValidationError,
  process_intake_submission,
)


def _baseline_payload() -> dict:
  """Returns a payload that the validator will reject for OTHER
  reasons (we just want to inspect ``errors`` for the two
  summary keys without depending on a real DB)."""
  return {
    "consumer_type": "consumer",
    "client_id": "client-test-001",
    "business_type": "Cafe",
    "business_name": "Test Cafe",
    "first_name": "Test",
    "last_name": "User",
    "email_address": "test@example.com",
    "business_start_date": "2025-01-01",
    "current_revenue": 0,
    "target_market": "111",
    "target_market_summary": "",
    "key_people_summary": "",
  }


def _collect_errors(payload: dict) -> dict:
  try:
    process_intake_submission(payload)
  except IntakeValidationError as exc:
    return dict(exc.errors)
  except Exception:
    return {}
  return {}


class IntakeRemediationGateBypassTest(unittest.TestCase):

  def test_bypass_active_target_market_summary_passes_gate(self) -> None:
    with mock.patch.object(
      intake_submit_service, "_SKIP_INTAKE_REMEDIATION_GATES", True,
    ):
      errors = _collect_errors(_baseline_payload())
    self.assertNotIn("target_market_summary", errors)

  def test_bypass_active_key_people_summary_passes_gate(self) -> None:
    with mock.patch.object(
      intake_submit_service, "_SKIP_INTAKE_REMEDIATION_GATES", True,
    ):
      errors = _collect_errors(_baseline_payload())
    self.assertNotIn("key_people_summary", errors)

  def test_bypass_inactive_both_summary_gates_fire(self) -> None:
    with mock.patch.object(
      intake_submit_service, "_SKIP_INTAKE_REMEDIATION_GATES", False,
    ):
      errors = _collect_errors(_baseline_payload())
    self.assertIn("target_market_summary", errors)
    self.assertIn("key_people_summary", errors)
    self.assertEqual(
      errors["target_market_summary"], "target_market_summary is required",
    )
    self.assertEqual(
      errors["key_people_summary"], "key_people_summary is required",
    )

  def test_financials_handler_has_bypass_flag(self) -> None:
    """Mirror-check: api_handlers/financials.py must expose the
    same flag with the same default so first-stage + second-stage
    bypass stay in lockstep."""
    from api_handlers import financials as financials_handler  # noqa: WPS433

    self.assertTrue(
      hasattr(financials_handler, "_SKIP_INTAKE_REMEDIATION_GATES"),
      "financials.py must declare _SKIP_INTAKE_REMEDIATION_GATES",
    )
    self.assertEqual(
      financials_handler._SKIP_INTAKE_REMEDIATION_GATES,
      intake_submit_service._SKIP_INTAKE_REMEDIATION_GATES,
      "financials.py and intake_submit_service.py bypass flags must agree",
    )


if __name__ == "__main__":
  unittest.main()
