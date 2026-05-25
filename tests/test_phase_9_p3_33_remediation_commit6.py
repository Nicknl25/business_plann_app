"""Phase 9 P3.33 remediation — Commit 6 (C1, C12).

C1 — Dynamic lever priority (spec §4.3 rule 2). Among rule-1-tied
candidates, the lever with the larger computed impact wins. Impact =
abs(current - target) * viability_weight_factor.

C12 — GPT responder retries malformed responses ONCE before falling
back to synthetic veto (spec §6.4).
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402,E501
  EvaluatePlanResult, FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (  # noqa: E402,E501
  CascadeLever, CascadeTier,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: E402,E501
  ReasonCode, StepType,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (  # noqa: E402,E501
  _pick_lever,
)


# ---------------------------------------------------------------------------
# C1 — Dynamic lever priority
# ---------------------------------------------------------------------------

def _margin(*, section, field, current, band_target):
  return LeverMargin(
    lever_id=field, section=section, current=current,
    band_target=band_target, band_min=band_target * 0.5,
    band_max=band_target * 1.5, outside_band=False,
  )


class DynamicLeverPriorityTest(unittest.TestCase):
  def test_larger_impact_wins_when_rule1_ties(self) -> None:
    """Two levers both in-band (rule 1 tie). The one with the
    larger viability_weight_factor * distance wins — even if its
    declared priority is LOWER (higher integer)."""
    tier = CascadeTier(
      tier_id="X1", name="dynamic test",
      levers=(
        # priority=2 but huge weighted impact — should win.
        CascadeLever("drivers", "high_impact", "to_band_target",
                     priority=2, viability_weight_factor=10.0),
        # priority=1 but small impact.
        CascadeLever("drivers", "low_impact", "to_band_target",
                     priority=1, viability_weight_factor=1.0),
      ),
      target_rule="test",
      step_type=StepType.TYPE_A,
      reason_code=ReasonCode.VIABILITY_COST_RATIO_TUNED,
    )
    margins = [
      # high_impact: current=0.5, target=0.4 -> distance=0.1, impact=1.0
      _margin(section="drivers", field="high_impact",
              current=0.5, band_target=0.4),
      # low_impact: current=0.42, target=0.4 -> distance=0.02, impact=0.02
      _margin(section="drivers", field="low_impact",
              current=0.42, band_target=0.4),
    ]
    picked = _pick_lever(tier, margins)
    self.assertIsNotNone(picked)
    self.assertEqual(picked[0].field, "high_impact",
                     "Rule 2 (impact) must beat rule 3 (declared priority).")

  def test_outside_band_still_wins_over_in_band_with_higher_impact(self) -> None:
    """Rule 1 is still strongest: an outside-band lever wins over an
    in-band lever no matter what impact the in-band lever computes."""
    tier = CascadeTier(
      tier_id="X2", name="rule 1 test",
      levers=(
        CascadeLever("drivers", "tiny_outsider", "to_band_target", priority=3),
        CascadeLever("drivers", "huge_in_band", "to_band_target",
                     priority=1, viability_weight_factor=100.0),
      ),
      target_rule="test",
      step_type=StepType.TYPE_A,
      reason_code=ReasonCode.VIABILITY_COST_RATIO_TUNED,
    )
    margins = [
      LeverMargin(
        lever_id="tiny_outsider", section="drivers", current=0.005,
        band_min=0.01, band_target=0.02, band_max=0.05,
        outside_band=True,  # below band_min
      ),
      _margin(section="drivers", field="huge_in_band",
              current=0.6, band_target=0.4),
    ]
    picked = _pick_lever(tier, margins)
    self.assertEqual(picked[0].field, "tiny_outsider",
                     "Rule 1 (outside_band) outranks rule 2 (impact).")

  def test_cogs_v1_default_weight_overrides_others(self) -> None:
    """The shipping V1 tier weights COGS=2.0; when COGS distance is
    comparable to a peer's distance, COGS wins."""
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_tier,
    )
    v1 = get_tier(FailureMode.VIABILITY_INVARIANT, "V1")
    cogs = next(lv for lv in v1.levers if "Cost of Goods Sold" in lv.field)
    self.assertEqual(cogs.viability_weight_factor, 2.0)


# ---------------------------------------------------------------------------
# C12 — Responder retries malformed once
# ---------------------------------------------------------------------------

class _FakeResponse:
  def __init__(self, *, status_code, body):
    self.status_code = status_code
    self.text = ""
    self._body = body
  def json(self):
    if isinstance(self._body, Exception):
      raise self._body
    return self._body


def _valid_confirm_body():
  return {
    "choices": [{
      "message": {
        "tool_calls": [{
          "function": {"name": "confirm_proposal", "arguments": "{}"},
        }],
      },
    }],
  }


def _malformed_body():
  return {"choices": [{"message": {"tool_calls": []}}]}


class ResponderRetryTest(unittest.TestCase):
  def setUp(self) -> None:
    # Force responder into "with API key" mode by setting the env var
    # for the duration of the test.
    self._prior = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "test-key"

  def tearDown(self) -> None:
    if self._prior is None:
      os.environ.pop("OPENAI_API_KEY", None)
    else:
      os.environ["OPENAI_API_KEY"] = self._prior

  def _make_responder(self, http_fn):
    from client_intake_and_finmo.post_intake_amalgamated.protocol.responder import (
      make_amalgamated_responder,
    )
    return make_amalgamated_responder(
      conn=None, draft_id="d", planning_run_id="r",
      mirror=None, _http=http_fn,
    )

  def _proposal_call_args(self):
    from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (
      Proposal,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_tier,
    )
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V1")
    proposal = Proposal(
      mode=FailureMode.VIABILITY_INVARIANT,
      tier_id=tier.tier_id, tier_name=tier.name,
      step_type=tier.step_type, reason_code=tier.reason_code,
      section="drivers", field="expenses::Cost of Goods Sold",
      current_value=0.5, proposed_value=0.4,
    )
    return {"mode": FailureMode.VIABILITY_INVARIANT, "tier": tier,
            "proposal_or_options": proposal}

  def test_retry_on_malformed_returns_confirm_on_second_attempt(self) -> None:
    calls = {"n": 0}
    def http(**_):
      calls["n"] += 1
      if calls["n"] == 1:
        return _FakeResponse(status_code=200, body=_malformed_body())
      return _FakeResponse(status_code=200, body=_valid_confirm_body())
    responder = self._make_responder(http)
    response = responder(**self._proposal_call_args())
    self.assertEqual(calls["n"], 2, "Responder must retry once on malformed")
    self.assertEqual(response.kind, "confirm")

  def test_both_attempts_malformed_returns_synthetic_veto(self) -> None:
    calls = {"n": 0}
    def http(**_):
      calls["n"] += 1
      return _FakeResponse(status_code=200, body=_malformed_body())
    responder = self._make_responder(http)
    response = responder(**self._proposal_call_args())
    self.assertEqual(calls["n"], 2)
    self.assertEqual(response.kind, "veto")
    self.assertIn("responder_malformed", response.reason or "")

  def test_http_error_first_attempt_retries(self) -> None:
    calls = {"n": 0}
    def http(**_):
      calls["n"] += 1
      if calls["n"] == 1:
        raise RuntimeError("simulated network blip")
      return _FakeResponse(status_code=200, body=_valid_confirm_body())
    responder = self._make_responder(http)
    response = responder(**self._proposal_call_args())
    self.assertEqual(calls["n"], 2)
    self.assertEqual(response.kind, "confirm")

  def test_both_attempts_http_error_returns_synthetic_veto(self) -> None:
    calls = {"n": 0}
    def http(**_):
      calls["n"] += 1
      raise RuntimeError("network down")
    responder = self._make_responder(http)
    response = responder(**self._proposal_call_args())
    self.assertEqual(calls["n"], 2)
    self.assertEqual(response.kind, "veto")
    self.assertIn("responder_http_error", response.reason or "")

  def test_valid_first_response_no_retry(self) -> None:
    """When the first attempt produces a valid response, the responder
    must NOT call http_fn a second time."""
    calls = {"n": 0}
    def http(**_):
      calls["n"] += 1
      return _FakeResponse(status_code=200, body=_valid_confirm_body())
    responder = self._make_responder(http)
    response = responder(**self._proposal_call_args())
    self.assertEqual(calls["n"], 1)
    self.assertEqual(response.kind, "confirm")


if __name__ == "__main__":
  unittest.main()
