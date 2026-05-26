"""Per-sub-contract acceptance tests for Contract 5
(IntakeDraftContract).

Spec: ``docs/architecture/p3_40_contract_5_intake_draft_spec.md``
section 6 Commit 1b. Top-level + Adjustment B tests land in
``test_p3_40_contract_5_intake_draft.py`` (Commit 1c).

Contract 5 has ZERO sub-contracts in Commit 1a (per F0 (b) +
sub-flag (c) DEFER). The "sub-contract tests" here cover:
- Required-field rejection for the 7 Tier-A fields.
- Optional fulfillment_json behavior per F1 (a) -- absent / present
  / empty / arbitrary keys.
- extra='forbid' top-level rejection per F6.
- Opacity confirmation -- Dict[str, Any] accepts arbitrary nested
  shapes.
"""

from __future__ import annotations

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

from client_intake_and_finmo.post_intake_contracts.intake_draft_contract import (  # noqa: E402
  IntakeDraftContract,
)
from _p3_40_contract_5_fixtures import (  # noqa: E402
  valid_intake_draft_dict,
)


# ---------------------------------------------------------------------------
# Tier A -- 7 required fields rejected when absent
# ---------------------------------------------------------------------------

class TierARequiredFieldsRejectionTest(unittest.TestCase):
  """The 7 consultant-produced or python-aggregated fields are
  required. Production today always writes them before post-intake
  reads -- the contract pins that expectation per PSL3 'don't
  loosen safety checks'."""

  def _assert_missing_field_rejected(self, field_name: str) -> None:
    payload = valid_intake_draft_dict()
    del payload[field_name]
    with self.assertRaises(ValidationError) as ctx:
      IntakeDraftContract.model_validate(payload)
    self.assertIn(field_name, str(ctx.exception))

  def test_missing_operating_model_json_rejected(self) -> None:
    self._assert_missing_field_rejected("operating_model_json")

  def test_missing_target_market_json_rejected(self) -> None:
    self._assert_missing_field_rejected("target_market_json")

  def test_missing_people_json_rejected(self) -> None:
    self._assert_missing_field_rejected("people_json")

  def test_missing_financials_json_rejected(self) -> None:
    self._assert_missing_field_rejected("financials_json")

  def test_missing_financials_year1_json_rejected(self) -> None:
    self._assert_missing_field_rejected("financials_year1_json")

  def test_missing_marketing_model_json_rejected(self) -> None:
    self._assert_missing_field_rejected("marketing_model_json")

  def test_missing_planning_context_summary_json_rejected(self) -> None:
    self._assert_missing_field_rejected("planning_context_summary_json")


# ---------------------------------------------------------------------------
# Tier F -- fulfillment_json Optional per Flag 1 (a)
# ---------------------------------------------------------------------------

class FulfillmentJsonOptionalTest(unittest.TestCase):
  """Flag 1 (a) disposition pinned: fulfillment_json is
  Optional[Dict[str, Any]] = None. Per trace T4 amended: patch-
  system writes only; SQL column legitimately NULL when no
  fulfillment.* patch ran. Downstream never structurally consumes
  (Contract 3 Tier-B closure-captured-but-explicitly-unused)."""

  def test_fulfillment_json_absent_accepted_default_none(self) -> None:
    payload = valid_intake_draft_dict(include_fulfillment_json=False)
    contract = IntakeDraftContract.model_validate(payload)
    self.assertIsNone(contract.fulfillment_json)

  def test_fulfillment_json_present_accepted(self) -> None:
    payload = valid_intake_draft_dict(include_fulfillment_json=True)
    contract = IntakeDraftContract.model_validate(payload)
    self.assertIsNotNone(contract.fulfillment_json)
    self.assertEqual(contract.fulfillment_json.get("fulfillment_model"), "test")

  def test_fulfillment_json_empty_dict_accepted(self) -> None:
    """No schema enforcement at the patch-system layer (Trace T4.1
    + v1 inventory section F-2 known bug). The contract reflects
    that reality: {} is a valid Dict[str, Any] for this field."""
    payload = valid_intake_draft_dict()
    payload["fulfillment_json"] = {}
    contract = IntakeDraftContract.model_validate(payload)
    self.assertEqual(contract.fulfillment_json, {})


# ---------------------------------------------------------------------------
# Flag 6 -- extra='forbid' top-level
# ---------------------------------------------------------------------------

class ExtraForbidTopLevelTest(unittest.TestCase):

  def test_unknown_top_level_field_rejected(self) -> None:
    """extra='forbid' top-level: a new field added by upstream
    without going through the spec process surfaces as a
    ValidationError. realism_memo_json is the headline case
    (excluded per F2; if intake starts writing it as a 9th
    contract field, this test fails until the spec adds it)."""
    payload = valid_intake_draft_dict()
    payload["realism_memo_json"] = {"diagnostic": "blob"}
    with self.assertRaises(ValidationError) as ctx:
      IntakeDraftContract.model_validate(payload)
    self.assertIn("realism_memo_json", str(ctx.exception))

  def test_business_fact_scalars_rejected_per_f3_exclude(self) -> None:
    """F3 disposition: business-fact scalar fields are NOT part of
    Contract 5 (Contract 3's BusinessFactsForSolverContract handles
    them opaquely). If a future caller tries to include them in
    the IntakeDraftContract payload, extra='forbid' rejects."""
    payload = valid_intake_draft_dict()
    payload["business_name"] = "Test Co"
    with self.assertRaises(ValidationError) as ctx:
      IntakeDraftContract.model_validate(payload)
    self.assertIn("business_name", str(ctx.exception))


# ---------------------------------------------------------------------------
# Opacity confirmation -- Dict[str, Any] accepts arbitrary shapes
# ---------------------------------------------------------------------------

class OpacityConfirmationTest(unittest.TestCase):
  """F0 (b) first-cut disposition: the REMAINING 6 fields
  (people_json, financials_json, financials_year1_json,
  marketing_model_json, planning_context_summary_json,
  fulfillment_json) are still opaque Dict[str, Any].
  operating_model_json + target_market_json were retrofitted in
  Commits 5b-3 + 5c-3 respectively -- their own arbitrary-shape
  acceptance is replaced by structural typing per Contracts 5b
  + 5c. Their typed-shape tests live at
  tests/test_p3_40_contract_5b_operating_model_json.py +
  tests/test_p3_40_contract_5c_target_market_json.py.

  Future retrofits (5d people_json, 5e/f/g/h python-aggregated
  shapes) follow the same pattern.
  """

  def test_arbitrary_nested_shape_accepted_for_other_dict_field(self) -> None:
    """The 6 remaining opaque Dict[str, Any] fields still accept
    arbitrary nested shapes. Pick people_json (Contract 5d
    R-residual -- next retrofit target)."""
    payload = valid_intake_draft_dict()
    payload["people_json"] = {
      "deeply_nested": {"a": [1, 2, {"b": None}]},
      "any_key": "any_value",
      "numeric_key": 42.5,
    }
    contract = IntakeDraftContract.model_validate(payload)
    self.assertEqual(
      contract.people_json["deeply_nested"]["a"][2]["b"], None,
    )

  def test_empty_dict_accepted_for_required_field(self) -> None:
    """Per spec section 5.3 (a): for opaque Dict[str, Any]
    fields, {} is valid. Downstream code's actual reads will
    fail when they try to extract keys -- but that's a consumer
    concern, not the contract gate's. (operating_model_json +
    target_market_json no longer opaque per 5b-3 + 5c-3
    retrofits; this test uses financials_json which remains
    opaque.)"""
    payload = valid_intake_draft_dict()
    payload["financials_json"] = {}
    contract = IntakeDraftContract.model_validate(payload)
    self.assertEqual(contract.financials_json, {})


if __name__ == "__main__":
  unittest.main()
