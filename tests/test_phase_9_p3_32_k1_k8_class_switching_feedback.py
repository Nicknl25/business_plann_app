"""Phase 9 P3.32 K1 K8 — class-switching enrichment regression tests.

ORIGINAL K8 SHAPE
K8 introduced
``intensity_classes_accepting_target_payroll_pct`` in lookup.py and
wired it into the (now-deleted) pre-K9 iterative refinement feedback
packet builder. The enrichment named the alternative
labor_intensity_class options whose policy bounds would accept the
GPT-emitted target_payroll_percent_of_revenue.

P3.32 K9 MIGRATION (FOLLOW-UP)
K9 deleted the pre-K9 iterative refinement loop and moved Handler C
to a tool-calling session. The K8 alternatives now flow as IN-LINE
fields inside the Tool 3 (`propose_payroll_headcount_schedule`)
structured_failures response, not as the buried-in-user-JSON
``context.alternative_labor_intensity_classes_for_actual_value``
field of the deleted feedback packet.

This regression-guard file now pins:
  - The lookup.py helper still exists and behaves correctly
    (unchanged from K8).
  - The K9 propose dispatcher attaches alternatives IN-LINE in
    structured_failures (new K9 location).
  - The deleted feedback-packet enrichment is gone (no
    "context.alternative_labor_intensity_classes_for_actual_value"
    in schedule.py source any more).
  - K1 F1+F2 (exhaustion handler excludes Payroll) and K1 F3+F4
    (target solver routes Payroll to Handler C) invariants
    preserved.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class TestIntensityClassesHelperBehavior(unittest.TestCase):
  """The lookup.py helper returns classes whose bounds include the
  value. Unchanged from K8; the helper is now also consumed by K9
  Tool 2's dispatcher."""

  def test_value_in_multiple_classes(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.lookup import (  # noqa: WPS433
      intensity_classes_accepting_target_payroll_pct,
    )
    alternatives = intensity_classes_accepting_target_payroll_pct(0.105)
    classes = {a.get("labor_intensity_class") for a in alternatives}
    self.assertIn("low", classes)
    self.assertIn("medium", classes)
    self.assertNotIn("high", classes)
    self.assertNotIn("expert", classes)

  def test_value_in_no_class(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.lookup import (  # noqa: WPS433
      intensity_classes_accepting_target_payroll_pct,
    )
    alternatives = intensity_classes_accepting_target_payroll_pct(0.95)
    self.assertEqual(alternatives, [])

  def test_value_in_all_classes(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.lookup import (  # noqa: WPS433
      intensity_classes_accepting_target_payroll_pct,
    )
    alternatives = intensity_classes_accepting_target_payroll_pct(0.30)
    classes = {a.get("labor_intensity_class") for a in alternatives}
    self.assertEqual(classes, {"low", "medium", "high", "expert"})

  def test_helper_returns_min_max_per_alternative(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.lookup import (  # noqa: WPS433
      intensity_classes_accepting_target_payroll_pct,
    )
    alternatives = intensity_classes_accepting_target_payroll_pct(0.20)
    for entry in alternatives:
      self.assertIn("labor_intensity_class", entry)
      self.assertIn("min_pct", entry)
      self.assertIn("max_pct", entry)
      self.assertGreater(entry["max_pct"], entry["min_pct"])

  def test_helper_deterministic_ordering(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.lookup import (  # noqa: WPS433
      intensity_classes_accepting_target_payroll_pct,
    )
    a1 = intensity_classes_accepting_target_payroll_pct(0.30)
    a2 = intensity_classes_accepting_target_payroll_pct(0.30)
    self.assertEqual(a1, a2)
    self.assertEqual(
      [e["labor_intensity_class"] for e in a1],
      sorted(e["labor_intensity_class"] for e in a1),
    )

  def test_helper_safe_on_invalid_input(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.lookup import (  # noqa: WPS433
      intensity_classes_accepting_target_payroll_pct,
    )
    self.assertEqual(intensity_classes_accepting_target_payroll_pct(None), [])  # type: ignore
    self.assertEqual(intensity_classes_accepting_target_payroll_pct("not a number"), [])  # type: ignore


class TestK8EnrichmentNowLivesInToolCallingSession(unittest.TestCase):
  """K9 moved the K8 enrichment from the pre-K9 iterative refinement
  feedback packet builder (deleted) to the propose tool's
  structured_failures response (new K9 location IN-LINE per failure
  entry)."""

  @staticmethod
  def _tool_calling_session_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_headcount",
      "tool_calling_session.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  @staticmethod
  def _schedule_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_headcount",
      "schedule.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  def test_tool_calling_session_imports_k8_helper(self) -> None:
    src = self._tool_calling_session_source()
    self.assertIn("intensity_classes_accepting_target_payroll_pct", src)

  def test_tool_calling_session_attaches_alternatives_inline_in_structured_failures(self) -> None:
    src = self._tool_calling_session_source()
    self.assertIn('failure["alternatives"]', src)
    self.assertIn('"accepting_classes"', src)

  def test_tool_calling_session_provides_guidance_string(self) -> None:
    src = self._tool_calling_session_source()
    # Guidance directs GPT to either move target into band or switch
    # class — wording is the K9-shaped variant (open-ended, no
    # "revise only" framing).
    self.assertIn("switch class", src)

  def test_schedule_no_longer_contains_pre_k9_buried_enrichment(self) -> None:
    """The pre-K9 enrichment placed K8 alternatives at
    failure["context"]["alternative_labor_intensity_classes_for_actual_value"]
    inside the deleted _build_payroll_iterative_feedback_packet
    function. After K9 that field name must no longer appear in
    schedule.py."""
    src = self._schedule_source()
    self.assertNotIn("alternative_labor_intensity_classes_for_actual_value", src)

  def test_schedule_no_longer_contains_deleted_feedback_packet_builder(self) -> None:
    """The pre-K9 _build_payroll_iterative_feedback_packet function
    is deleted (replaced by the K9 propose tool dispatcher)."""
    src = self._schedule_source()
    self.assertNotIn("def _build_payroll_iterative_feedback_packet", src)


class TestK9PropozeDispatcherAttachesK8EnrichmentEndToEnd(unittest.TestCase):
  """End-to-end: simulate the propose tool's A.2 failure path on a
  target_payroll_percent_of_revenue out_of_range code and verify the
  K8 enrichment appears IN-LINE in structured_failures."""

  def test_a2_out_of_range_failure_carries_alternatives_inline(self) -> None:
    from unittest import mock  # noqa: WPS433
    from client_intake_and_finmo.fail_fast.common import (  # noqa: WPS433
      FailFastError,
    )
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_propose,
    )

    fake_exc = FailFastError(
      code="payroll_headcount_schedule_validation_failed",
      message="payroll_headcount_schedule_validation_failed",
      details={
        "errors": [
          "payroll_headcount_target_payroll_percent_of_revenue_out_of_policy_range:value=0.105:min=0.16:max=0.7",
        ],
      },
    )
    with mock.patch(
      "client_intake_and_finmo.post_intake_headcount.schedule.validate_payroll_headcount_contract_payload",
      side_effect=fake_exc,
    ):
      outcome = _dispatch_propose(
        {"contract_version": "x"},
        draft_id="d",
        client_id="c",
        model_input_json={},
        business_facts={},
        ops_json={},
        resolved_people_json={},
      )
    structured = outcome.tool_result["structured_failures"]
    self.assertGreater(len(structured), 0)
    failure = structured[0]
    self.assertEqual(failure["field"], "target_payroll_percent_of_revenue")
    self.assertEqual(failure["category"], "out_of_range")
    self.assertIn("alternatives", failure)
    classes = {
      entry.get("labor_intensity_class")
      for entry in failure["alternatives"]["accepting_classes"]
    }
    self.assertIn("low", classes)
    self.assertIn("medium", classes)


class TestK8PreservesK1F1ThroughF7Invariants(unittest.TestCase):
  """K8 (and now K9) operates within K1 F1-F7's structural closures
  and must not regress them."""

  def test_exhaustion_handler_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertNotIn("expenses::Payroll", GPT_AUTHORED_LEVER_IDS)

  def test_target_solver_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _HANDLER_C_OWNED_LEVER_IDS,
    )
    self.assertIn("expenses::Payroll", _HANDLER_C_OWNED_LEVER_IDS)


if __name__ == "__main__":
  unittest.main()
