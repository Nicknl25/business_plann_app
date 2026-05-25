"""Phase 9 P3.33 Phase 3 step 8a — responder.

Hermetic tests for ``protocol.responder.make_amalgamated_responder``.
No live OpenAI calls; an injected ``_http`` seam simulates the
response payload. Confirms:

  - render_mirror_for_proposal produces a §6.3 Type A or Type B prompt
    body with the proposal fields filled in.
  - OPENAI_API_KEY unset -> synthetic veto with the
    'openai_api_key_unset_synthetic_veto' reason.
  - HTTP exception -> synthetic veto with responder_http_error: prefix.
  - HTTP non-200 -> synthetic veto with responder_http_non_200: prefix.
  - Malformed body shapes (no tool call, non-JSON arguments, unknown
    function) -> synthetic veto with responder_malformed: prefix.
  - confirm_proposal / veto_proposal / choose_option / other_proposal
    tool calls parse into matching ProposalResponse kinds.
  - The four response-tool specs are present in the OpenAI request
    tools array.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any, Dict
from unittest.mock import patch


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402
  FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.mirror import Mirror  # noqa: E402
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (  # noqa: E402
  get_tier,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.responder import (  # noqa: E402
  make_amalgamated_responder, render_mirror_for_proposal,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (  # noqa: E402,E501
  Proposal,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: E402,E501
  ReasonCode, StepType,
)


class _FakeResp:
  def __init__(self, *, status_code: int, body: Any):
    self.status_code = status_code
    self.text = json.dumps(body) if not isinstance(body, str) else body
    self._body = body

  def json(self):
    if isinstance(self._body, dict):
      return self._body
    raise ValueError("non_json_body_in_fake")


def _proposal_type_a():
  return Proposal(
    mode=FailureMode.VIABILITY_INVARIANT,
    tier_id="V1", tier_name="Cost-ratio tuning",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.VIABILITY_COST_RATIO_TUNED,
    section="drivers", field="expenses::Cost of Goods Sold",
    current_value=0.72, proposed_value=0.65,
    band_min=0.55, band_target=0.65, band_max=0.78,
    pinning_summary="in band with headroom",
    rationale_text="V1 cost-ratio tuning",
  )


def _proposal_type_b_options():
  base = dict(
    mode=FailureMode.VIABILITY_INVARIANT,
    tier_id="V3", tier_name="Pricing",
    step_type=StepType.TYPE_B,
    reason_code=ReasonCode.VIABILITY_PRICING_ADJUSTED,
    section="operating_model", field="unit_price",
  )
  return [
    Proposal(**base, option_id="A", proposed_value=30.0,
             summary="Premium positioning", tradeoff_text="margin up, volume risk"),
    Proposal(**base, option_id="B", proposed_value=15.0,
             summary="Value positioning", tradeoff_text="volume up, margin down"),
  ]


class RenderMirrorTest(unittest.TestCase):
  def test_type_a_prompt_includes_proposal_fields(self) -> None:
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V1")
    text = render_mirror_for_proposal(
      mirror=None, proposal_or_options=_proposal_type_a(),
      mode=FailureMode.VIABILITY_INVARIANT, tier=tier,
    )
    self.assertIn("RESTRUCTURE PROPOSAL", text)
    self.assertIn("Cost-ratio tuning", text)
    self.assertIn("expenses::Cost of Goods Sold", text)
    self.assertIn("0.7200", text)
    self.assertIn("0.6500", text)
    self.assertIn("confirm_proposal", text)

  def test_type_b_prompt_lists_options(self) -> None:
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V3")
    text = render_mirror_for_proposal(
      mirror=None, proposal_or_options=_proposal_type_b_options(),
      mode=FailureMode.VIABILITY_INVARIANT, tier=tier,
    )
    self.assertIn("RESTRUCTURE CHOICE", text)
    self.assertIn("Premium positioning", text)
    self.assertIn("Value positioning", text)
    self.assertIn("choose_option", text)

  def test_business_facts_block_included(self) -> None:
    mirror = Mirror(business_facts={"naics_6": "722511", "business_stage": "ramp"})
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V1")
    text = render_mirror_for_proposal(
      mirror=mirror, proposal_or_options=_proposal_type_a(),
      mode=FailureMode.VIABILITY_INVARIANT, tier=tier,
    )
    self.assertIn("Business facts", text)
    self.assertIn("722511", text)


class SyntheticVetoFallbackTest(unittest.TestCase):
  def test_no_api_key_returns_synthetic_veto(self) -> None:
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
      responder = make_amalgamated_responder()
      r = responder(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "veto")
      self.assertIn("openai_api_key_unset_synthetic_veto", r.reason)


class HttpErrorFallbackTest(unittest.TestCase):
  def test_http_exception_returns_synthetic_veto(self) -> None:
    def boom(**_): raise RuntimeError("connection_reset")
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      responder = make_amalgamated_responder(_http=boom)
      r = responder(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "veto")
      self.assertIn("responder_http_error", r.reason)

  def test_non_200_returns_synthetic_veto(self) -> None:
    def http_500(**_): return _FakeResp(status_code=500, body="server_error")
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      responder = make_amalgamated_responder(_http=http_500)
      r = responder(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "veto")
      self.assertIn("responder_http_non_200:500", r.reason)


class ToolCallParsingTest(unittest.TestCase):
  def _envelope(self, *, name: str, args: Dict[str, Any]):
    return {
      "choices": [{"message": {"tool_calls": [{
        "function": {"name": name, "arguments": json.dumps(args)},
      }]}}],
    }

  def _responder_returning(self, body):
    def http(**_): return _FakeResp(status_code=200, body=body)
    return make_amalgamated_responder(_http=http)

  def test_confirm_proposal_parsed(self) -> None:
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      r = self._responder_returning(
        self._envelope(name="confirm_proposal", args={}),
      )(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "confirm")
      self.assertTrue(r.validated)

  def test_veto_proposal_with_reason_parsed(self) -> None:
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      r = self._responder_returning(self._envelope(
        name="veto_proposal", args={"reason": "premium positioning"},
      ))(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "veto")
      self.assertIn("premium positioning", r.reason)

  def test_choose_option_parsed(self) -> None:
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      r = self._responder_returning(self._envelope(
        name="choose_option", args={"option_id": "B"},
      ))(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V3"),
        proposal_or_options=_proposal_type_b_options(),
      )
      self.assertEqual(r.kind, "choose")
      self.assertEqual(r.option_id, "B")

  def test_other_proposal_parsed(self) -> None:
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      r = self._responder_returning(self._envelope(
        name="other_proposal",
        args={"section": "drivers", "field": "expenses::Cost of Goods Sold",
              "value": 0.62, "reason": "airline supply"},
      ))(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "other")
      self.assertEqual(r.section, "drivers")
      self.assertAlmostEqual(r.value, 0.62)


class MalformedResponseTest(unittest.TestCase):
  def _responder_returning(self, body):
    def http(**_): return _FakeResp(status_code=200, body=body)
    return make_amalgamated_responder(_http=http)

  def test_no_tool_calls_returns_veto(self) -> None:
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      r = self._responder_returning({"choices": [{"message": {}}]})(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "veto")
      self.assertIn("responder_malformed:no_tool_calls", r.reason)

  def test_unknown_function_returns_veto(self) -> None:
    body = {"choices": [{"message": {"tool_calls": [
      {"function": {"name": "made_up", "arguments": "{}"}},
    ]}}]}
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      r = self._responder_returning(body)(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "veto")
      self.assertIn("responder_malformed:unknown_tool:made_up", r.reason)

  def test_arguments_not_json_returns_veto(self) -> None:
    body = {"choices": [{"message": {"tool_calls": [
      {"function": {"name": "confirm_proposal", "arguments": "not-json"}},
    ]}}]}
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      r = self._responder_returning(body)(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
      self.assertEqual(r.kind, "veto")
      self.assertIn("responder_malformed:arguments_not_json", r.reason)


class RequestShapeTest(unittest.TestCase):
  def test_tools_array_contains_all_four_response_tools(self) -> None:
    captured: Dict[str, Any] = {}
    def http(**kwargs):
      captured.update(kwargs)
      return _FakeResp(status_code=200, body={"choices": [{"message": {
        "tool_calls": [{"function": {
          "name": "confirm_proposal", "arguments": "{}",
        }}],
      }}]})
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
      responder = make_amalgamated_responder(_http=http)
      responder(
        mode=FailureMode.VIABILITY_INVARIANT,
        tier=get_tier(FailureMode.VIABILITY_INVARIANT, "V1"),
        proposal_or_options=_proposal_type_a(),
      )
    payload = captured.get("payload") or {}
    tool_names = sorted(
      t["function"]["name"] for t in (payload.get("tools") or [])
      if isinstance(t, dict)
    )
    self.assertEqual(tool_names, [
      "choose_option", "confirm_proposal", "other_proposal", "veto_proposal",
    ])
    self.assertEqual(payload.get("tool_choice"), "required")
    self.assertEqual(payload.get("temperature"), 0.0)
    self.assertEqual(payload.get("seed"), 1729)


if __name__ == "__main__":
  unittest.main()
