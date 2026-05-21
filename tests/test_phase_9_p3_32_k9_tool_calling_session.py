"""Phase 9 P3.32 K9 — Handler C tool-calling migration tests.

M1 (schema correctness, 3 tests):
  - Tool 1 schema strict-valid
  - Tool 2 schema strict-valid
  - Tool 3 schema matches the existing contract schema builder

M2 (tool function semantics, 8 tests):
  - Tool 1 returns bounds for each known class
  - Tool 1 includes all_class_bounds
  - Tool 1 rejects unknown class
  - Tool 2 accepting + rejecting partition (parametrized)
  - Tool 2 empty accepting for out-of-envelope target
  - Tool 3 routes through existing validator chain
  - Tool 3 attaches K8 enrichment IN-LINE on A.2 out_of_range failures
  - Tool 3 returns compacted_violations on A.3 economic feasibility failure

M3 (session-loop integration, 6 tests, mocked LLM):
  - Session commits on first validator-accepted propose call
  - Session replaces candidate on subsequent validator-accepted call
    (most-recent-wins)
  - Session exhausts hard cap without accepted -> exhausted status
  - Session handles unknown tool name gracefully
  - Session handles tool_arguments_not_json gracefully
  - Session seeds initial prompt from external_seed_text
    (previous_contract_failure external-caller seed)

Plus K1 F1-F7 invariant preservation regression tests.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from typing import Any, Dict, List, Optional
from unittest import mock


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# ---------------------------------------------------------------------------
# M1 — Tool schema correctness
# ---------------------------------------------------------------------------


class TestM1ToolSchemas(unittest.TestCase):
  """Tool schemas conform to Responses API strict-mode rules."""

  def test_tool_1_get_bounds_schema(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _build_get_bounds_tool_definition,
    )
    td = _build_get_bounds_tool_definition()
    self.assertEqual(td["type"], "function")
    self.assertEqual(td["name"], "get_payroll_revenue_sanity_bounds")
    self.assertTrue(td["strict"])
    params = td["parameters"]
    self.assertEqual(params["type"], "object")
    self.assertFalse(params["additionalProperties"])
    self.assertIn("labor_intensity_class", params["required"])
    self.assertEqual(
      set(params["properties"]["labor_intensity_class"]["enum"]),
      {"low", "medium", "high", "expert"},
    )

  def test_tool_2_find_classes_schema(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _build_find_classes_tool_definition,
    )
    td = _build_find_classes_tool_definition()
    self.assertEqual(td["name"], "find_classes_accepting_target_payroll_pct")
    self.assertTrue(td["strict"])
    params = td["parameters"]
    self.assertEqual(params["type"], "object")
    self.assertFalse(params["additionalProperties"])
    self.assertIn("target_payroll_percent_of_revenue", params["required"])
    self.assertEqual(
      params["properties"]["target_payroll_percent_of_revenue"]["type"],
      "number",
    )

  def test_tool_3_propose_schema_reuses_contract_builder(self) -> None:
    """Per K9 design memo Q3: the propose tool reuses the existing
    strict-mode schema builder verbatim. Verify by building the
    schema both ways and checking they're identical at the parameter
    level."""
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _build_propose_tool_definition,
    )
    from client_intake_and_finmo.post_intake_mapping import (  # noqa: WPS433
      post_intake_gpt_contract_openai_schema,
    )
    td = _build_propose_tool_definition(business_naics=None)
    expected = post_intake_gpt_contract_openai_schema(
      contract_name="payroll_headcount_schedule",
      business_naics=None,
    )
    self.assertEqual(td["name"], "propose_payroll_headcount_schedule")
    self.assertTrue(td["strict"])
    self.assertEqual(td["parameters"], expected)


# ---------------------------------------------------------------------------
# M2 — Tool function semantics
# ---------------------------------------------------------------------------


class TestM2Tool1GetBounds(unittest.TestCase):
  """get_payroll_revenue_sanity_bounds returns canonical bounds."""

  @staticmethod
  def _default_policy() -> Dict[str, Any]:
    return {
      "policy_code": "default",
      "payroll_revenue_sanity_bounds": {
        "low":    {"min_pct": 0.06, "max_pct": 0.45},
        "medium": {"min_pct": 0.10, "max_pct": 0.55},
        "high":   {"min_pct": 0.16, "max_pct": 0.70},
        "expert": {"min_pct": 0.18, "max_pct": 0.80},
      },
      "payroll_revenue_sanity_tolerance_pct": 0.03,
      "payroll_revenue_sanity_relative_tolerance": 0.20,
    }

  def test_returns_bounds_for_each_class(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_get_bounds,
    )
    policy = self._default_policy()
    for cls, exp_min, exp_max in (
      ("low", 0.06, 0.45),
      ("medium", 0.10, 0.55),
      ("high", 0.16, 0.70),
      ("expert", 0.18, 0.80),
    ):
      with self.subTest(cls=cls):
        out = _dispatch_get_bounds({"labor_intensity_class": cls}, policy=policy)
        self.assertEqual(out["labor_intensity_class"], cls)
        self.assertAlmostEqual(out["min_pct"], exp_min)
        self.assertAlmostEqual(out["max_pct"], exp_max)

  def test_includes_all_class_bounds(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_get_bounds,
    )
    policy = self._default_policy()
    out = _dispatch_get_bounds({"labor_intensity_class": "high"}, policy=policy)
    all_bounds = out["all_class_bounds"]
    self.assertEqual(len(all_bounds), 4)
    self.assertEqual(
      {entry["labor_intensity_class"] for entry in all_bounds},
      {"low", "medium", "high", "expert"},
    )

  def test_rejects_unknown_class(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_get_bounds,
    )
    policy = self._default_policy()
    out = _dispatch_get_bounds({"labor_intensity_class": "ultra"}, policy=policy)
    self.assertEqual(out["error"], "labor_intensity_class_not_in_policy")
    self.assertIn("low", out["valid_classes"])

  def test_includes_tolerance_and_source_table(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_get_bounds,
    )
    policy = self._default_policy()
    out = _dispatch_get_bounds({"labor_intensity_class": "medium"}, policy=policy)
    self.assertEqual(out["source_table"], "post_intake_headcount_policy_lookup")
    self.assertAlmostEqual(out["tolerance_pct"], 0.03)
    self.assertAlmostEqual(out["relative_tolerance"], 0.20)


class TestM2Tool2FindClasses(unittest.TestCase):
  """find_classes_accepting_target_payroll_pct returns accepting +
  rejecting partition."""

  def test_value_in_multiple_classes(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_find_classes,
    )
    out = _dispatch_find_classes({"target_payroll_percent_of_revenue": 0.105})
    accepting = {entry["labor_intensity_class"] for entry in out["accepting_classes"]}
    rejecting = {entry["labor_intensity_class"] for entry in out["rejecting_classes"]}
    self.assertEqual(accepting, {"low", "medium"})
    self.assertEqual(rejecting, {"high", "expert"})

  def test_value_outside_envelope_returns_empty_accepting(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_find_classes,
    )
    out = _dispatch_find_classes({"target_payroll_percent_of_revenue": 0.95})
    self.assertEqual(out["accepting_classes"], [])
    # All four classes should be in rejecting
    self.assertEqual(len(out["rejecting_classes"]), 4)

  def test_non_numeric_input(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_find_classes,
    )
    out = _dispatch_find_classes({"target_payroll_percent_of_revenue": "garbage"})
    self.assertEqual(out["error"], "target_must_be_numeric")


class TestM2Tool3Propose(unittest.TestCase):
  """propose_payroll_headcount_schedule routes through validator chain
  and surfaces K8 enrichment IN-LINE on A.2 out_of_range failures."""

  def test_a2_out_of_range_failure_attaches_k8_alternatives_in_line(self) -> None:
    """When the propose tool receives an A.2 out_of_range failure on
    target_payroll_percent_of_revenue, the structured_failures entry
    must carry alternatives.accepting_classes IN-LINE (not nested in
    a deeply-buried context field as in the deleted pre-K9 packet
    builder)."""
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_propose,
    )
    from client_intake_and_finmo.fail_fast.common import (  # noqa: WPS433
      FailFastError,
    )

    # Simulate the A.2 validator path: build a fake FailFastError
    # carrying the A.2 wrapper code + a translatable token.
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
    tr = outcome.tool_result
    self.assertFalse(tr["validator_accepted"])
    self.assertEqual(tr["validator_error_code"], "payroll_headcount_schedule_validation_failed")
    structured = tr["structured_failures"]
    self.assertGreater(len(structured), 0)
    failure = structured[0]
    self.assertEqual(failure["field"], "target_payroll_percent_of_revenue")
    self.assertEqual(failure["category"], "out_of_range")
    self.assertIn("alternatives", failure)
    accepting = {
      entry["labor_intensity_class"]
      for entry in failure["alternatives"]["accepting_classes"]
    }
    # 0.105 should be accepted by low and medium
    self.assertIn("low", accepting)
    self.assertIn("medium", accepting)
    self.assertIn("guidance", failure)

  def test_a3_economic_feasibility_failure_returns_compacted_violations(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_propose,
    )
    from client_intake_and_finmo.fail_fast.common import (  # noqa: WPS433
      FailFastError,
    )

    fake_exc = FailFastError(
      code="payroll_revenue_economic_feasibility_failed",
      message="economic feasibility failed",
      details={
        "violations": [
          {"quarter_index": 5, "revenue": 100000, "payroll": 50000, "payroll_percent_of_revenue": 0.50},
        ],
      },
    )
    # Patch _assert_payroll_contract_economic_feasible_for_retry to raise.
    with mock.patch(
      "client_intake_and_finmo.post_intake_headcount.schedule._assert_payroll_contract_economic_feasible_for_retry",
      side_effect=fake_exc,
    ), mock.patch(
      "client_intake_and_finmo.post_intake_headcount.schedule.validate_payroll_headcount_contract_payload",
      return_value={"target_payroll_percent_of_revenue": 0.5},
    ), mock.patch(
      "client_intake_and_finmo.post_intake_headcount.schedule.build_payroll_headcount_payload_from_contract",
      return_value={"quarter_totals": []},
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
    tr = outcome.tool_result
    self.assertFalse(tr["validator_accepted"])
    self.assertEqual(tr["validator_error_code"], "payroll_revenue_economic_feasibility_failed")
    self.assertIn("compacted_violations", tr)

  def test_success_returns_built_schedule_payload(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      _dispatch_propose,
    )
    fake_contract = {
      "labor_intensity_class": "medium",
      "target_payroll_percent_of_revenue": 0.45,
      "wage_positioning_tier": "market",
      "capacity_labor_model": "labor_driven",
    }
    fake_payload = {"quarter_totals": [{"quarter_index": 1, "payroll": 100000}], "rows": []}
    with mock.patch(
      "client_intake_and_finmo.post_intake_headcount.schedule.validate_payroll_headcount_contract_payload",
      return_value=fake_contract,
    ), mock.patch(
      "client_intake_and_finmo.post_intake_headcount.schedule.build_payroll_headcount_payload_from_contract",
      return_value=fake_payload,
    ), mock.patch(
      "client_intake_and_finmo.post_intake_headcount.schedule._assert_payroll_contract_economic_feasible_for_retry",
      return_value=None,
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
    self.assertTrue(outcome.tool_result["validator_accepted"])
    self.assertEqual(outcome.tool_result["summary"]["labor_intensity_class"], "medium")
    self.assertIs(outcome.schedule_payload, fake_payload)


# ---------------------------------------------------------------------------
# K9 follow-up — intake-implied operating intensity (Sunny regression fix)
# ---------------------------------------------------------------------------


class TestK9SunnyFixIntakeImpliedOperatingIntensity(unittest.TestCase):
  """The Sunny Glaze Donuts regression investigation
  (docs/architecture/p3_32_k9_regression_sunny_glaze_donuts_
  investigation.md) identified that K9's removal of pre-K9
  class-selection anchoring (the "first choose" framing + the
  medium-class example) left Handler C without an operating-
  intensity signal for borderline businesses.

  The fix: surface the intake-implied operating-intensity ratio
  (intake_payroll_year1 / intake_revenue_year1) to Handler C as
  one signal for class selection. Universal across NAICS. Intake
  numbers are NOT binding (per intake_non_binding_policy already
  in user_context); the ratio is informational.
  """

  def test_helper_returns_ratio_when_both_intake_fields_present(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      _intake_implied_operating_intensity,
    )
    out = _intake_implied_operating_intensity(
      financials={"payroll_total_year1": 160000, "current_revenue": 487000},
      year1={"company_revenue_total_year1": 487000},
    )
    self.assertAlmostEqual(out["implied_payroll_percent_of_revenue"], 0.3285, places=4)
    self.assertEqual(out["intake_payroll_year1"], 160000)
    self.assertEqual(out["intake_revenue_year1"], 487000)

  def test_helper_handles_low_payroll_high_revenue_scaleup(self) -> None:
    """Skyward-shape: very low intake payroll vs huge revenue. The
    implied ratio is below all class bounds. The note must instruct
    GPT to use operating-model judgment for scale-up cases."""
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      _intake_implied_operating_intensity,
    )
    out = _intake_implied_operating_intensity(
      financials={"payroll_total_year1": 637537, "current_revenue": 88452000},
      year1={"company_revenue_total_year1": 88452000},
    )
    self.assertLess(out["implied_payroll_percent_of_revenue"], 0.05)
    self.assertIn("scale-ups", out["note"])

  def test_helper_returns_none_ratio_when_inputs_missing(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      _intake_implied_operating_intensity,
    )
    out = _intake_implied_operating_intensity(financials={}, year1={})
    self.assertIsNone(out["implied_payroll_percent_of_revenue"])

  def test_helper_returns_none_ratio_when_revenue_zero(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      _intake_implied_operating_intensity,
    )
    out = _intake_implied_operating_intensity(
      financials={"payroll_total_year1": 50000, "current_revenue": 0},
      year1={"company_revenue_total_year1": 0},
    )
    self.assertIsNone(out["implied_payroll_percent_of_revenue"])

  def test_helper_safe_on_non_numeric_inputs(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      _intake_implied_operating_intensity,
    )
    out = _intake_implied_operating_intensity(
      financials={"payroll_total_year1": "abc", "current_revenue": "xyz"},
      year1={},
    )
    self.assertIsNone(out["implied_payroll_percent_of_revenue"])

  def test_helper_uses_year1_company_revenue_first(self) -> None:
    """Resolution order: year1.company_revenue_total_year1 >
    year1.revenue_total_year1 > financials.current_revenue."""
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      _intake_implied_operating_intensity,
    )
    out = _intake_implied_operating_intensity(
      financials={"payroll_total_year1": 100000, "current_revenue": 999999},
      year1={"company_revenue_total_year1": 500000, "revenue_total_year1": 200000},
    )
    self.assertAlmostEqual(out["implied_payroll_percent_of_revenue"], 0.20, places=4)

  def test_helper_note_references_intake_non_binding(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      _intake_implied_operating_intensity,
    )
    out = _intake_implied_operating_intensity(financials={}, year1={})
    self.assertIn("NOT BINDING", out["note"])
    self.assertIn("intake_non_binding_policy", out["note"])
    self.assertIn("find_classes_accepting_target_payroll_pct", out["note"])

  def test_system_prompt_includes_class_selection_guidance(self) -> None:
    """Verify the SYSTEM_PROMPT carries the operating-model-aware
    class selection guidance added as part of the Sunny fix."""
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      SYSTEM_PROMPT,
    )
    self.assertIn("intake_implied_operating_intensity", SYSTEM_PROMPT)
    self.assertIn("match labor_intensity_class", SYSTEM_PROMPT)
    self.assertIn("not to the highest", SYSTEM_PROMPT.replace("\n", " ").lower())

  def test_system_prompt_does_not_re_introduce_pre_k9_pinning(self) -> None:
    """Class-selection guidance must NOT re-introduce the pre-K9
    'revise only named fields' rule or the 'first choose' pinning
    framing. The fix is a class-selection signal, not a pinning
    directive."""
    from client_intake_and_finmo.post_intake_headcount.tool_calling_session import (  # noqa: WPS433
      SYSTEM_PROMPT,
    )
    self.assertNotIn("revise only", SYSTEM_PROMPT.lower())
    self.assertNotIn("revise ONLY", SYSTEM_PROMPT)
    self.assertNotIn("first choose", SYSTEM_PROMPT.lower())

  def test_schedule_user_context_includes_intake_implied_field(self) -> None:
    """The estimate_payroll_headcount_schedule_with_gpt function must
    surface intake_implied_operating_intensity into the user_context
    block that gets passed into the tool-calling session."""
    import os  # noqa: WPS433
    here = os.path.abspath(os.path.dirname(__file__))
    python_root = os.path.abspath(os.path.join(here, os.pardir, "python"))
    src_path = os.path.join(
      python_root,
      "client_intake_and_finmo", "post_intake_headcount", "schedule.py",
    )
    with open(src_path, "r", encoding="utf-8") as fh:
      src = fh.read()
    # The user_context dict literal contains the new key.
    self.assertIn('"intake_implied_operating_intensity":', src)
    self.assertIn("_intake_implied_operating_intensity(", src)


# ---------------------------------------------------------------------------
# M3 — Session-loop integration (mocked LLM)
# ---------------------------------------------------------------------------


def _fake_turn_factory(turns: List[Dict[str, Any]]):
  """Build a fake call_gpt_responses_api_turn that replays a fixed
  sequence of turn responses. Each turn is a dict matching the
  shape returned by call_gpt_responses_api_turn."""
  state = {"index": 0}

  def _fake_turn(**kwargs):
    idx = state["index"]
    if idx >= len(turns):
      # Default: GPT stops calling the tool.
      return {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [],
        "raw_assistant_items": [],
        "assistant_message_text": "(stopped)",
        "detail": "",
      }
    resp = turns[idx]
    state["index"] += 1
    return resp

  return _fake_turn


def _make_propose_call(call_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
  return {
    "id": call_id,
    "call_id": call_id,
    "name": "propose_payroll_headcount_schedule",
    "arguments": json.dumps(args),
  }


class TestM3SessionLoop(unittest.TestCase):
  """The session loop drives the conversation with the GPT turn
  function and commits the most-recent validator_accepted propose
  call."""

  def _base_session_kwargs(self) -> Dict[str, Any]:
    return {
      "request_context": {"business_identity": {"business_name": "x"}},
      "policy": {
        "policy_code": "default",
        "payroll_revenue_sanity_bounds": {
          "low":    {"min_pct": 0.06, "max_pct": 0.45},
          "medium": {"min_pct": 0.10, "max_pct": 0.55},
          "high":   {"min_pct": 0.16, "max_pct": 0.70},
          "expert": {"min_pct": 0.18, "max_pct": 0.80},
        },
      },
      "business_naics": None,
      "draft_id": "d",
      "client_id": "c",
      "model_input_json": {},
      "business_facts": {},
      "ops_json": {},
      "resolved_people_json": {},
    }

  def test_session_commits_on_validator_accepted_propose(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    fake_payload = {"rows": [], "quarter_totals": []}
    turns = [
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [_make_propose_call("c1", {"contract_version": "x"})],
        "raw_assistant_items": [],
      },
      # Second turn: GPT stops calling tools (it sees accepted=true).
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [],
        "raw_assistant_items": [],
      },
    ]
    with mock.patch.object(
      tcs,
      "_dispatch_propose",
      return_value=tcs._ProposeDispatchOutcome(
        tool_result={"validator_accepted": True, "summary": {}},
        schedule_payload=fake_payload,
      ),
    ):
      result = tcs.run_payroll_tool_calling_session(
        external_seed_text=None,
        _call_gpt_turn=_fake_turn_factory(turns),
        **self._base_session_kwargs(),
      )
    self.assertEqual(result.status, "verified")
    self.assertIs(result.schedule_payload, fake_payload)
    self.assertEqual(result.tool_calls_used, 1)
    self.assertEqual(result.verified_commit_call_n, 1)

  def test_session_most_recent_validator_accepted_wins(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    first_payload = {"marker": "first"}
    second_payload = {"marker": "second"}
    outcomes = [
      tcs._ProposeDispatchOutcome(
        tool_result={"validator_accepted": True, "summary": {}},
        schedule_payload=first_payload,
      ),
      tcs._ProposeDispatchOutcome(
        tool_result={"validator_accepted": True, "summary": {}},
        schedule_payload=second_payload,
      ),
    ]
    state = {"idx": 0}
    def _fake_dispatch(*args, **kwargs):
      out = outcomes[state["idx"]]
      state["idx"] += 1
      return out

    turns = [
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [_make_propose_call("c1", {"contract_version": "x"})],
        "raw_assistant_items": [],
      },
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [_make_propose_call("c2", {"contract_version": "x"})],
        "raw_assistant_items": [],
      },
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [],
        "raw_assistant_items": [],
      },
    ]
    with mock.patch.object(tcs, "_dispatch_propose", side_effect=_fake_dispatch):
      result = tcs.run_payroll_tool_calling_session(
        external_seed_text=None,
        _call_gpt_turn=_fake_turn_factory(turns),
        **self._base_session_kwargs(),
      )
    self.assertEqual(result.status, "verified")
    self.assertIs(result.schedule_payload, second_payload)

  def test_session_exhausts_hard_cap_without_accepted(self) -> None:
    """Hard cap with no validator_accepted -> status=exhausted, no
    schedule_payload."""
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    rejected_outcome = tcs._ProposeDispatchOutcome(
      tool_result={
        "validator_accepted": False,
        "validator_error_code": "payroll_headcount_schedule_validation_failed",
        "validator_error_text": "rejected",
      },
      schedule_payload=None,
    )
    # Hard cap is 10; GPT keeps calling.
    turns = [
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [_make_propose_call(f"c{i}", {"contract_version": "x"})],
        "raw_assistant_items": [],
      }
      for i in range(1, 12)
    ]
    with mock.patch.object(tcs, "_dispatch_propose", return_value=rejected_outcome):
      result = tcs.run_payroll_tool_calling_session(
        external_seed_text=None,
        _call_gpt_turn=_fake_turn_factory(turns),
        **self._base_session_kwargs(),
      )
    self.assertEqual(result.status, "exhausted")
    self.assertIsNone(result.schedule_payload)
    self.assertEqual(result.tool_calls_used, tcs.HARD_CAP_TOOL_CALLS)
    self.assertEqual(
      result.last_validator_error_code,
      "payroll_headcount_schedule_validation_failed",
    )

  def test_session_handles_unknown_tool_name(self) -> None:
    """Unknown tool name -> returns error to GPT, session continues."""
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    fake_payload = {"rows": []}
    turns = [
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [
          {"call_id": "c1", "name": "some_fake_tool", "arguments": "{}"},
        ],
        "raw_assistant_items": [],
      },
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [_make_propose_call("c2", {"contract_version": "x"})],
        "raw_assistant_items": [],
      },
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [],
        "raw_assistant_items": [],
      },
    ]
    with mock.patch.object(
      tcs,
      "_dispatch_propose",
      return_value=tcs._ProposeDispatchOutcome(
        tool_result={"validator_accepted": True, "summary": {}},
        schedule_payload=fake_payload,
      ),
    ):
      result = tcs.run_payroll_tool_calling_session(
        external_seed_text=None,
        _call_gpt_turn=_fake_turn_factory(turns),
        **self._base_session_kwargs(),
      )
    self.assertEqual(result.status, "verified")
    # Two tool calls used (the unknown one was still counted as a call).
    self.assertEqual(result.tool_calls_used, 2)
    self.assertEqual(result.tool_call_history[0].result.get("error"), "unknown_tool_some_fake_tool")

  def test_session_handles_tool_arguments_not_json(self) -> None:
    """Malformed JSON arguments -> session returns error to GPT and
    continues (no tool_calls_used increment for the malformed call)."""
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    turns = [
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [
          {
            "call_id": "c1",
            "name": "get_payroll_revenue_sanity_bounds",
            "arguments": "not-json{",
          },
        ],
        "raw_assistant_items": [],
      },
      {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [],
        "raw_assistant_items": [],
      },
    ]
    result = tcs.run_payroll_tool_calling_session(
      external_seed_text=None,
      _call_gpt_turn=_fake_turn_factory(turns),
      **self._base_session_kwargs(),
    )
    # No verified candidate ever ran -> exhausted (here actually
    # gpt_stopped after the bad call).
    self.assertEqual(result.status, "exhausted")

  def test_session_seeds_external_caller_text(self) -> None:
    """The external_seed_text arg is included in the initial user
    prompt — verify it appears in the input_items passed to the GPT
    turn."""
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    captured: Dict[str, Any] = {"input_items_first_call": None}

    def _capturing_turn(**kwargs):
      if captured["input_items_first_call"] is None:
        captured["input_items_first_call"] = copy.deepcopy(kwargs["input_items"])
      return {
        "decision_source": "python_proposer_plus_gpt_critic",
        "tool_calls": [],
        "raw_assistant_items": [],
      }

    tcs.run_payroll_tool_calling_session(
      external_seed_text="MARKER_SEED_TEXT_FOR_TEST_xyz123",
      _call_gpt_turn=_capturing_turn,
      **self._base_session_kwargs(),
    )
    serialized = json.dumps(captured["input_items_first_call"])
    self.assertIn("MARKER_SEED_TEXT_FOR_TEST_xyz123", serialized)


# ---------------------------------------------------------------------------
# K9 preserves K1 F1-F7 invariants
# ---------------------------------------------------------------------------


class TestK9PreservesK1F1ThroughF7Invariants(unittest.TestCase):
  """K9 operates inside K1 F1-F7's structural closures and must
  not regress them."""

  def test_exhaustion_handler_still_excludes_payroll(self) -> None:
    """K1 F1+F2: GPT exhaustion handler authority excludes Payroll."""
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertNotIn("expenses::Payroll", GPT_AUTHORED_LEVER_IDS)

  def test_target_solver_still_owns_payroll_via_handler_c(self) -> None:
    """K1 F3+F4: target solver routes Payroll to Handler C."""
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _HANDLER_C_OWNED_LEVER_IDS,
    )
    self.assertIn("expenses::Payroll", _HANDLER_C_OWNED_LEVER_IDS)

  def test_route_payroll_feasibility_to_handler_c_still_exists(self) -> None:
    """K1 F5+F7 routing primitive must remain importable + callable."""
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      route_payroll_feasibility_to_handler_c,
    )
    self.assertTrue(callable(route_payroll_feasibility_to_handler_c))

  def test_apply_payroll_schedule_to_state_still_exists(self) -> None:
    """K1 F6 apply chain primitive must remain importable + callable."""
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      apply_payroll_schedule_to_state,
    )
    self.assertTrue(callable(apply_payroll_schedule_to_state))

  def test_mirror_flavor_1_invariants_still_exported(self) -> None:
    """F6 three-surface assertions must remain available."""
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: WPS433
      assert_finmo_payroll_matches_headcount_schedule,
      assert_payroll_headcount_model_input_applied,
    )
    self.assertTrue(callable(assert_finmo_payroll_matches_headcount_schedule))
    self.assertTrue(callable(assert_payroll_headcount_model_input_applied))


# ---------------------------------------------------------------------------
# K9 deletes the pre-K9 iterative refinement machinery
# ---------------------------------------------------------------------------


class TestK9DeletesPreK9Machinery(unittest.TestCase):
  """The pre-K9 iterative-refinement machinery must be deleted, not
  routed around. Per memory feedback_remove_dont_just_cutoff: delete
  dead code as part of each module change."""

  def test_payroll_iter_gpt_call_count_contextvar_deleted(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import schedule as _payroll_schedule  # noqa: WPS433
    self.assertFalse(hasattr(_payroll_schedule, "_PAYROLL_ITER_GPT_CALL_COUNT"))

  def test_payroll_iterative_hard_cap_rounds_deleted(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import schedule as _payroll_schedule  # noqa: WPS433
    self.assertFalse(hasattr(_payroll_schedule, "_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS"))

  def test_iterative_machinery_fail_fast_deleted(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import schedule as _payroll_schedule  # noqa: WPS433
    self.assertFalse(hasattr(_payroll_schedule, "_payroll_iterative_machinery_fail_fast"))

  def test_assert_iterative_state_intact_deleted(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import schedule as _payroll_schedule  # noqa: WPS433
    self.assertFalse(hasattr(_payroll_schedule, "_assert_payroll_iterative_state_intact"))

  def test_assert_iterative_budget_decoupled_deleted(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import schedule as _payroll_schedule  # noqa: WPS433
    self.assertFalse(hasattr(_payroll_schedule, "_assert_payroll_iterative_budget_decoupled"))

  def test_build_iterative_feedback_packet_deleted(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import schedule as _payroll_schedule  # noqa: WPS433
    self.assertFalse(hasattr(_payroll_schedule, "_build_payroll_iterative_feedback_packet"))

  def test_new_tool_calling_session_module_present(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    self.assertTrue(callable(tcs.run_payroll_tool_calling_session))
    self.assertEqual(tcs.HARD_CAP_TOOL_CALLS, 10)


if __name__ == "__main__":
  unittest.main()
