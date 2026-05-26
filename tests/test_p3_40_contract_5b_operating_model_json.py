"""Structural typing tests for Contract 5b
(OperatingModelJsonContract sub-contract retrofit).

Per spec §6 Commit 5b-2 + §0 value-constraint policy: tests
verify JSON SHAPE only, not VALUES.

What's tested:
  - Each sub-contract accepts a minimal valid payload
  - Each sub-contract rejects missing required (non-nullable) fields
  - Nullable-required (F7) fields accept None and accept absent
  - Production extras (F1) accepted when present, accepted when absent
  - extra='ignore' (F4) graceful pass-through for unknown fields
  - Wrong outer JSON type rejected (string where list expected, etc.)
  - Nested sub-contract typing propagates (List[ProductContract] etc.)

What's NOT tested (banned per §0):
  - Literal-rejection: bare str accepts ANY string including
    non-schema enum values. Tested via positive acceptance.
  - min_length / max_length / pattern: not enforced; not tested.
  - cross-field invariants: none exist; not tested.
  - enum-value typo-rejection: bare str accepts typos. Tested
    via positive acceptance.
  - value range constraints: not enforced; not tested.

4 test classes:
  - ProductContractTest
  - LobModelContractTest
  - MilestoneContractTest
  - OperatingModelJsonContractTest
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

from client_intake_and_finmo.post_intake_contracts.operating_model_json_contract import (  # noqa: E402
  OPERATING_MODEL_JSON_STAGE_LABEL,
  LobModelContract,
  MilestoneContract,
  OperatingModelJsonContract,
  ProductContract,
)
from _p3_40_contract_5b_fixtures import (  # noqa: E402
  valid_lob_model_dict,
  valid_milestone_dict,
  valid_operating_model_json_dict,
  valid_product_dict,
)


# ---------------------------------------------------------------------------
# ProductContract (9 fields)
# ---------------------------------------------------------------------------

class ProductContractTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = ProductContract.model_validate(valid_product_dict())
    self.assertIsInstance(contract, ProductContract)
    self.assertEqual(contract.unit_cadence, "weekly")

  def test_missing_required_non_nullable_field_rejected(self) -> None:
    """7 of 9 fields are non-nullable required; pick one."""
    payload = valid_product_dict()
    del payload["product_name"]
    with self.assertRaises(ValidationError) as ctx:
      ProductContract.model_validate(payload)
    self.assertIn("product_name", str(ctx.exception))

  def test_nullable_optional_fields_accept_none(self) -> None:
    """operating_periods_per_year + utilization_rate Optional
    per the nested schema."""
    payload = valid_product_dict(
      operating_periods_per_year=None, utilization_rate=None,
    )
    contract = ProductContract.model_validate(payload)
    self.assertIsNone(contract.operating_periods_per_year)
    self.assertIsNone(contract.utilization_rate)

  def test_nullable_optional_fields_accept_absent(self) -> None:
    payload = valid_product_dict()
    del payload["operating_periods_per_year"]
    del payload["utilization_rate"]
    contract = ProductContract.model_validate(payload)
    self.assertIsNone(contract.operating_periods_per_year)
    self.assertIsNone(contract.utilization_rate)

  def test_bare_str_unit_cadence_accepts_any_string(self) -> None:
    """Per §0 / F5: unit_cadence schema enum NOT pinned to
    Literal. Any string accepted (e.g., 'biennial' which is
    NOT a schema enum value)."""
    payload = valid_product_dict(unit_cadence="biennial")
    contract = ProductContract.model_validate(payload)
    self.assertEqual(contract.unit_cadence, "biennial")

  def test_unit_price_zero_accepted(self) -> None:
    """Per §0 / F5: unit_price > 0 NOT enforced even though
    system prompt at intake_consultant.py:622 says non-zero."""
    payload = valid_product_dict(unit_price=0.0)
    contract = ProductContract.model_validate(payload)
    self.assertEqual(contract.unit_price, 0.0)

  def test_extra_keys_ignored(self) -> None:
    """F4: extra='ignore' on all sub-contracts."""
    payload = valid_product_dict()
    payload["future_field_v2"] = "tolerated"
    contract = ProductContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "future_field_v2"))


# ---------------------------------------------------------------------------
# LobModelContract (2 fields)
# ---------------------------------------------------------------------------

class LobModelContractTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = LobModelContract.model_validate(valid_lob_model_dict())
    self.assertIsInstance(contract, LobModelContract)
    self.assertEqual(len(contract.products), 1)

  def test_products_typed_as_product_contract_list(self) -> None:
    """T5 nested-object STRUCTURE preserved per §0 exception."""
    contract = LobModelContract.model_validate(valid_lob_model_dict())
    self.assertIsInstance(contract.products[0], ProductContract)

  def test_empty_products_list_accepted(self) -> None:
    """Per §0 / spec §4: schema minItems=1 NOT enforced via
    Field(min_length=1)."""
    payload = valid_lob_model_dict(products=[])
    contract = LobModelContract.model_validate(payload)
    self.assertEqual(contract.products, [])

  def test_missing_lob_name_rejected(self) -> None:
    payload = valid_lob_model_dict()
    del payload["lob_name"]
    with self.assertRaises(ValidationError):
      LobModelContract.model_validate(payload)

  def test_nested_product_validation_propagates(self) -> None:
    """Invalid nested product surfaces as ValidationError on
    the LOB-level validation."""
    bad_product = valid_product_dict()
    del bad_product["unit_name"]
    payload = valid_lob_model_dict(products=[bad_product])
    with self.assertRaises(ValidationError) as ctx:
      LobModelContract.model_validate(payload)
    self.assertIn("unit_name", str(ctx.exception))


# ---------------------------------------------------------------------------
# MilestoneContract (2 fields)
# ---------------------------------------------------------------------------

class MilestoneContractTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = MilestoneContract.model_validate(valid_milestone_dict())
    self.assertEqual(contract.description, "Open second location")

  def test_missing_required_field_rejected(self) -> None:
    payload = valid_milestone_dict()
    del payload["description"]
    with self.assertRaises(ValidationError):
      MilestoneContract.model_validate(payload)

  def test_extra_keys_ignored(self) -> None:
    payload = valid_milestone_dict()
    payload["completion_status"] = "in_progress"
    contract = MilestoneContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "completion_status"))


# ---------------------------------------------------------------------------
# OperatingModelJsonContract (27 typed top-level fields)
# ---------------------------------------------------------------------------

class OperatingModelJsonContractTest(unittest.TestCase):

  def test_valid_full_payload_accepted(self) -> None:
    contract = OperatingModelJsonContract.model_validate(
      valid_operating_model_json_dict()
    )
    self.assertEqual(contract.consumer_type, "consumer")
    self.assertEqual(contract.business_naics_6, "722515")

  def test_missing_non_nullable_required_field_rejected(self) -> None:
    """Pick one of the 13 non-nullable required schema fields."""
    payload = valid_operating_model_json_dict()
    del payload["consumer_type"]
    with self.assertRaises(ValidationError) as ctx:
      OperatingModelJsonContract.model_validate(payload)
    self.assertIn("consumer_type", str(ctx.exception))

  def test_all_10_nullable_required_fields_accept_none(self) -> None:
    """F7: 10 nullable-required schema fields type as
    Optional[X] = None. Each accepts explicit None."""
    payload = valid_operating_model_json_dict(
      business_stage=None, lob_models=None, unit_name=None,
      unit_description=None, unit_cadence=None,
      units_per_week_capacity=None, units_per_period_capacity=None,
      operating_periods_per_year=None, utilization_rate=None,
      unit_price=None,
    )
    contract = OperatingModelJsonContract.model_validate(payload)
    for field_name in (
      "business_stage", "lob_models", "unit_name", "unit_description",
      "unit_cadence", "units_per_week_capacity",
      "units_per_period_capacity", "operating_periods_per_year",
      "utilization_rate", "unit_price",
    ):
      self.assertIsNone(getattr(contract, field_name))

  def test_all_10_nullable_required_fields_accept_absent(self) -> None:
    """F7: legacy-draft safety. Key entirely absent accepted
    (defaults to None)."""
    payload = valid_operating_model_json_dict()
    for field_name in (
      "business_stage", "lob_models", "unit_name", "unit_description",
      "unit_cadence", "units_per_week_capacity",
      "units_per_period_capacity", "operating_periods_per_year",
      "utilization_rate", "unit_price",
    ):
      payload.pop(field_name, None)
    contract = OperatingModelJsonContract.model_validate(payload)
    self.assertIsNone(contract.business_stage)
    self.assertIsNone(contract.lob_models)

  def test_production_extras_accepted_when_absent(self) -> None:
    """F1: 4 production extras typed as Optional[X] = None.
    Absence is a legitimate state (conditional per T3 (a))."""
    payload = valid_operating_model_json_dict(
      include_production_extras=False,
    )
    contract = OperatingModelJsonContract.model_validate(payload)
    self.assertIsNone(contract.business_naics_6)
    self.assertIsNone(contract.competitive_advantage)
    self.assertIsNone(contract.business_type_candidates)
    self.assertIsNone(contract.business_type_candidates_locked)

  def test_bare_str_enum_vocabularies_accept_non_schema_values(self) -> None:
    """Per §0 / F5: NO Literal narrowing for the 5 enum
    vocabularies. consumer_type accepts 'franchise' (NOT a
    schema enum), sales_modality accepts 'phygital', etc."""
    payload = valid_operating_model_json_dict(
      consumer_type="franchise",
      sales_modality="phygital",
      geographic_scope="multi-state",
      capacity_driver="capital",
      unit_cadence="biennial",
    )
    contract = OperatingModelJsonContract.model_validate(payload)
    self.assertEqual(contract.consumer_type, "franchise")
    self.assertEqual(contract.sales_modality, "phygital")
    self.assertEqual(contract.geographic_scope, "multi-state")
    self.assertEqual(contract.capacity_driver, "capital")
    self.assertEqual(contract.unit_cadence, "biennial")

  def test_countries_accepts_mixed_types(self) -> None:
    """Per §0: countries types as List[Any] (item-type pinning
    BANNED). Schema says items are strings; contract accepts
    anything in the list."""
    payload = valid_operating_model_json_dict(
      countries=[None, 1, "US", {"nested": "weirdness"}],
    )
    contract = OperatingModelJsonContract.model_validate(payload)
    self.assertEqual(len(contract.countries), 4)

  def test_empty_milestones_accepted(self) -> None:
    """Per §0 / §4: schema minItems=1 on milestones NOT
    enforced."""
    payload = valid_operating_model_json_dict(include_milestones=False)
    contract = OperatingModelJsonContract.model_validate(payload)
    self.assertEqual(contract.milestones, [])

  def test_extra_keys_ignored_legacy_fallbacks(self) -> None:
    """F2: legacy fallback fields naics_code + business_naics
    accepted via extra='ignore' rather than as typed fields."""
    payload = valid_operating_model_json_dict()
    payload["naics_code"] = "722515"
    payload["business_naics"] = "722515"
    contract = OperatingModelJsonContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "naics_code"))
    self.assertFalse(hasattr(contract, "business_naics"))

  def test_lob_models_typed_as_lob_model_contract_list(self) -> None:
    """T5 nested-object STRUCTURE preserved per §0 exception."""
    payload = valid_operating_model_json_dict(include_lob_models=True)
    contract = OperatingModelJsonContract.model_validate(payload)
    self.assertIsInstance(contract.lob_models[0], LobModelContract)
    self.assertIsInstance(contract.lob_models[0].products[0], ProductContract)

  def test_nested_product_validation_propagates_through_top_level(self) -> None:
    """A bad nested ProductContract field surfaces at the
    top-level OperatingModelJsonContract validation."""
    payload = valid_operating_model_json_dict(include_lob_models=True)
    del payload["lob_models"][0]["products"][0]["unit_name"]
    with self.assertRaises(ValidationError) as ctx:
      OperatingModelJsonContract.model_validate(payload)
    self.assertIn("unit_name", str(ctx.exception))

  def test_milestone_validation_propagates_through_top_level(self) -> None:
    payload = valid_operating_model_json_dict()
    del payload["milestones"][0]["timing"]
    with self.assertRaises(ValidationError) as ctx:
      OperatingModelJsonContract.model_validate(payload)
    self.assertIn("timing", str(ctx.exception))

  def test_wrong_outer_json_type_for_countries_rejected(self) -> None:
    """countries is required List[Any]. A string is NOT a list
    -- the structural type mismatch is THE thing the contract
    fires on per §0 (catches malformed JSON, schema-version
    drift)."""
    payload = valid_operating_model_json_dict()
    payload["countries"] = "US"  # string, not list
    with self.assertRaises(ValidationError):
      OperatingModelJsonContract.model_validate(payload)


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

class ModuleConstantsTest(unittest.TestCase):

  def test_stage_label_value_pinned(self) -> None:
    """F3: discoverable identifier, no new gate site."""
    self.assertEqual(
      OPERATING_MODEL_JSON_STAGE_LABEL,
      "INTAKE_DRAFT::operating_model_json",
    )

  def test_top_level_contract_has_27_typed_fields(self) -> None:
    """13 non-nullable required + 10 nullable-required Optional
    + 4 production extras = 27. Pins the field set so a future
    schema change is a deliberate edit, not silent drift."""
    self.assertEqual(len(OperatingModelJsonContract.model_fields), 27)


if __name__ == "__main__":
  unittest.main()
