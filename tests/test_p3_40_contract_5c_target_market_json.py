"""Structural typing tests for Contract 5c
(TargetMarketJsonContract sub-contract retrofit).

Per spec §6 Commit 5c-2 + §0 value-constraint policy: tests
verify JSON SHAPE only, not VALUES.

What's tested:
  - Each sub-contract accepts a minimal valid payload
  - Each sub-contract rejects missing required fields
  - Nullable-required (F6) fields accept None and accept absent
  - 3 CSV production extras (F1) accepted when present + absent
  - extra='ignore' (F3) graceful pass-through
  - Wrong outer JSON type rejected
  - Nested sub-contract typing propagates (List[GenderAgeIntentEntry] etc.)
  - Bare-str enum vocabularies accept non-schema values
  - b2b_naics_6 accepts non-pattern items (per §0 pattern BANNED)
  - b2b_naics_6 accepts >20 items + empty list (per §0
    minItems/maxItems BANNED)
  - acs_codes inside SelectionsEntry accepts mixed types
    (List[Any] per F8)

What's NOT tested (banned per §0):
  - Literal-rejection (no Literals)
  - age_min/age_max + income_min/income_max invariants
  - CSV-extras consistency cross-check
  - conditional-required (b2b/mixed implies b2b_* populated)
  - confidence numeric range
  - b2b_naics_6 pattern / length-bound rejection

5 test classes per spec §6.
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

from client_intake_and_finmo.post_intake_contracts.target_market_json_contract import (  # noqa: E402
  TARGET_MARKET_JSON_STAGE_LABEL,
  GenderAgeIntentEntry,
  IncomeIntentEntry,
  SelectionsEntry,
  TargetMarketJsonContract,
)
from _p3_40_contract_5c_fixtures import (  # noqa: E402
  valid_gender_age_intent_entry_dict,
  valid_income_intent_entry_dict,
  valid_selections_entry_dict,
  valid_target_market_json_dict,
)


# ---------------------------------------------------------------------------
# GenderAgeIntentEntry (3 fields)
# ---------------------------------------------------------------------------

class GenderAgeIntentEntryTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = GenderAgeIntentEntry.model_validate(
      valid_gender_age_intent_entry_dict()
    )
    self.assertEqual(contract.gender_focus, "all")

  def test_missing_required_field_rejected(self) -> None:
    payload = valid_gender_age_intent_entry_dict()
    del payload["gender_focus"]
    with self.assertRaises(ValidationError):
      GenderAgeIntentEntry.model_validate(payload)

  def test_bare_str_gender_focus_accepts_non_schema_value(self) -> None:
    """Per §0 / F4: gender_focus schema enum (female/male/all)
    NOT pinned to Literal. Any string accepted (e.g.,
    'non-binary' which is NOT a schema enum value)."""
    payload = valid_gender_age_intent_entry_dict(gender_focus="non-binary")
    contract = GenderAgeIntentEntry.model_validate(payload)
    self.assertEqual(contract.gender_focus, "non-binary")

  def test_age_min_greater_than_max_accepted(self) -> None:
    """Per §0 / F5: age_min <= age_max cross-field invariant
    REJECTED. Reversed values pass structural typing."""
    payload = valid_gender_age_intent_entry_dict(age_min=80.0, age_max=18.0)
    contract = GenderAgeIntentEntry.model_validate(payload)
    self.assertEqual(contract.age_min, 80.0)


# ---------------------------------------------------------------------------
# IncomeIntentEntry (2 fields)
# ---------------------------------------------------------------------------

class IncomeIntentEntryTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = IncomeIntentEntry.model_validate(
      valid_income_intent_entry_dict()
    )
    self.assertEqual(contract.income_min, 30000.0)

  def test_missing_required_field_rejected(self) -> None:
    payload = valid_income_intent_entry_dict()
    del payload["income_max"]
    with self.assertRaises(ValidationError):
      IncomeIntentEntry.model_validate(payload)

  def test_income_min_greater_than_max_accepted(self) -> None:
    """Per §0 / F5: income_min <= income_max cross-field
    invariant REJECTED."""
    payload = valid_income_intent_entry_dict(
      income_min=200000.0, income_max=20000.0,
    )
    contract = IncomeIntentEntry.model_validate(payload)
    self.assertEqual(contract.income_min, 200000.0)


# ---------------------------------------------------------------------------
# SelectionsEntry (2 fields)
# ---------------------------------------------------------------------------

class SelectionsEntryTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = SelectionsEntry.model_validate(
      valid_selections_entry_dict()
    )
    self.assertEqual(contract.segment, "Education")

  def test_missing_required_field_rejected(self) -> None:
    payload = valid_selections_entry_dict()
    del payload["acs_codes"]
    with self.assertRaises(ValidationError):
      SelectionsEntry.model_validate(payload)

  def test_bare_str_segment_accepts_non_schema_value(self) -> None:
    """Per §0 / F4: segment schema enum (Education / Household
    Structure / Housing Economics / Employment) NOT pinned."""
    payload = valid_selections_entry_dict(segment="Future Custom Segment")
    contract = SelectionsEntry.model_validate(payload)
    self.assertEqual(contract.segment, "Future Custom Segment")

  def test_acs_codes_accepts_mixed_types(self) -> None:
    """Per §0 / F8: acs_codes types as List[Any] (item-type
    pinning BANNED even though schema says items are strings)."""
    payload = valid_selections_entry_dict(
      acs_codes=[None, 1, "B15003_017E", {"nested": True}],
    )
    contract = SelectionsEntry.model_validate(payload)
    self.assertEqual(len(contract.acs_codes), 4)


# ---------------------------------------------------------------------------
# TargetMarketJsonContract (14 typed top-level fields)
# ---------------------------------------------------------------------------

class TargetMarketJsonContractTest(unittest.TestCase):

  def test_valid_consumer_only_payload_accepted(self) -> None:
    contract = TargetMarketJsonContract.model_validate(
      valid_target_market_json_dict()
    )
    self.assertEqual(contract.consumer_type, "consumer")
    self.assertIsNone(contract.b2b_naics_6)
    self.assertIsNone(contract.target_market_b2b_industry)

  def test_valid_b2b_payload_accepted(self) -> None:
    contract = TargetMarketJsonContract.model_validate(
      valid_target_market_json_dict(
        consumer_type="b2b",
        include_b2b_arrays=True,
        include_csv_extras=True,
      )
    )
    self.assertEqual(contract.consumer_type, "b2b")
    self.assertEqual(contract.b2b_naics_6, ["722515", "722513"])
    self.assertEqual(contract.target_market_b2b_industry, "722515,722513")

  def test_missing_non_nullable_required_field_rejected(self) -> None:
    payload = valid_target_market_json_dict()
    del payload["consumer_type"]
    with self.assertRaises(ValidationError) as ctx:
      TargetMarketJsonContract.model_validate(payload)
    self.assertIn("consumer_type", str(ctx.exception))

  def test_all_7_nullable_required_fields_accept_none(self) -> None:
    """F6: 7 nullable-required schema fields type as
    Optional[X] = None. Each accepts explicit None."""
    payload = valid_target_market_json_dict(
      gender_age_intent=None, income_intent=None, selections=None,
      b2b_industry_terms=None, b2b_naics_6=None,
      b2b_size_bands=None, b2b_age_bands=None,
    )
    contract = TargetMarketJsonContract.model_validate(payload)
    for field_name in (
      "gender_age_intent", "income_intent", "selections",
      "b2b_industry_terms", "b2b_naics_6",
      "b2b_size_bands", "b2b_age_bands",
    ):
      self.assertIsNone(getattr(contract, field_name))

  def test_all_7_nullable_required_fields_accept_absent(self) -> None:
    """F6: legacy-draft safety. Key entirely absent accepted
    (defaults to None)."""
    payload = valid_target_market_json_dict(
      include_gender_age=False, include_income=False,
      include_selections=False, include_b2b_arrays=False,
    )
    contract = TargetMarketJsonContract.model_validate(payload)
    self.assertIsNone(contract.gender_age_intent)
    self.assertIsNone(contract.b2b_naics_6)

  def test_production_extras_accepted_when_absent(self) -> None:
    """F1: 3 CSV extras typed as Optional[str] = None. Absence
    is the consumer-only state (T3)."""
    contract = TargetMarketJsonContract.model_validate(
      valid_target_market_json_dict(include_csv_extras=False)
    )
    self.assertIsNone(contract.target_market_b2b_industry)
    self.assertIsNone(contract.target_market_b2b_size)
    self.assertIsNone(contract.target_market_b2b_age)

  def test_bare_str_consumer_type_accepts_non_schema_value(self) -> None:
    """Per §0 / F4: NO Literal narrowing. consumer_type accepts
    'franchise' (NOT a schema enum value)."""
    payload = valid_target_market_json_dict(consumer_type="franchise")
    contract = TargetMarketJsonContract.model_validate(payload)
    self.assertEqual(contract.consumer_type, "franchise")

  def test_b2b_naics_6_accepts_non_pattern_items(self) -> None:
    """Per §0 / F4: b2b_naics_6 schema pattern ^[0-9]{6}$ NOT
    enforced. Items type as Any -- non-NAICS strings accepted."""
    payload = valid_target_market_json_dict(
      include_b2b_arrays=True,
      b2b_naics_6=["ABC123", "not-a-naics", "722515"],
    )
    contract = TargetMarketJsonContract.model_validate(payload)
    self.assertEqual(contract.b2b_naics_6, ["ABC123", "not-a-naics", "722515"])

  def test_b2b_naics_6_accepts_25_items(self) -> None:
    """Per §0 / F4: schema maxItems=20 NOT enforced."""
    payload = valid_target_market_json_dict(
      include_b2b_arrays=True,
      b2b_naics_6=[f"7225{i:02d}" for i in range(25)],
    )
    contract = TargetMarketJsonContract.model_validate(payload)
    self.assertEqual(len(contract.b2b_naics_6), 25)

  def test_b2b_naics_6_accepts_empty_list(self) -> None:
    """Per §0 / F4: schema minItems=1 NOT enforced."""
    payload = valid_target_market_json_dict(
      include_b2b_arrays=True, b2b_naics_6=[],
    )
    contract = TargetMarketJsonContract.model_validate(payload)
    self.assertEqual(contract.b2b_naics_6, [])

  def test_b2b_size_bands_accepts_non_schema_enum_items(self) -> None:
    """Per §0 / F4: b2b_size_bands items enum NOT pinned to
    Literal."""
    payload = valid_target_market_json_dict(
      include_b2b_arrays=True,
      b2b_size_bands=["custom-tiny", "custom-huge"],
    )
    contract = TargetMarketJsonContract.model_validate(payload)
    self.assertEqual(contract.b2b_size_bands, ["custom-tiny", "custom-huge"])

  def test_nested_gender_age_validation_propagates(self) -> None:
    """A bad nested GenderAgeIntentEntry field surfaces at the
    top-level TargetMarketJsonContract validation."""
    payload = valid_target_market_json_dict(include_gender_age=True)
    del payload["gender_age_intent"][0]["age_min"]
    with self.assertRaises(ValidationError) as ctx:
      TargetMarketJsonContract.model_validate(payload)
    self.assertIn("age_min", str(ctx.exception))

  def test_extra_keys_ignored(self) -> None:
    """F3: extra='ignore' on top-level. Future schema-version
    drift tolerated."""
    payload = valid_target_market_json_dict()
    payload["future_field_v2"] = "tolerated"
    contract = TargetMarketJsonContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "future_field_v2"))

  def test_wrong_outer_json_type_for_b2b_naics_6_rejected(self) -> None:
    """b2b_naics_6 is Optional[List[Any]]. A string is NOT a
    list -- structural type mismatch is THE thing the contract
    fires on per §0."""
    payload = valid_target_market_json_dict()
    payload["b2b_naics_6"] = "722515"  # string, not list
    with self.assertRaises(ValidationError):
      TargetMarketJsonContract.model_validate(payload)


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

class ModuleConstantsTest(unittest.TestCase):

  def test_stage_label_value_pinned(self) -> None:
    self.assertEqual(
      TARGET_MARKET_JSON_STAGE_LABEL,
      "INTAKE_DRAFT::target_market_json",
    )

  def test_top_level_contract_has_14_typed_fields(self) -> None:
    """4 non-nullable required + 7 nullable-required Optional +
    3 production extras = 14. Pins the field set."""
    self.assertEqual(len(TargetMarketJsonContract.model_fields), 14)


if __name__ == "__main__":
  unittest.main()
