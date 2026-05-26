"""Structural typing tests for Contract 5d (PeopleJsonContract
sub-contract retrofit).

Per spec §6 Commit 5d-2 + §0 value-constraint policy: tests
verify JSON SHAPE only, not VALUES.

What's tested:
  - Each sub-contract accepts a minimal valid payload
  - Each sub-contract rejects missing required fields
  - Nullable-required (F7) and production-popped (F1) fields
    accept None + accept absent + accept populated
  - extra='ignore' (F3) graceful pass-through (including
    PersonContract legacy fallback fields per F2)
  - Wrong outer JSON type rejected
  - Nested sub-contract typing propagates
  - minItems=1 REJECTED per §0 (empty people / inferred_roles
    accepted)
  - annual_wage = 0 and negative accepted (per §0 -- no
    Field(gt=0))
  - months_until_hire negative accepted (per §0 -- no
    Field(ge=0))
  - experience_years free-form string accepted per F8

What's NOT tested (banned per §0):
  - Literal-rejection (no Literals -- ZERO enum vocabularies in
    this schema)
  - Pattern-rejection (no patterns)
  - min_length / max_length rejection (none enforced)
  - Cross-field invariants (none exist)
  - inferred_roles_summary == format_roles_summary consistency

4 test classes per spec §6.
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

from client_intake_and_finmo.post_intake_contracts.people_json_contract import (  # noqa: E402
  PEOPLE_JSON_STAGE_LABEL,
  InferredRoleContract,
  PeopleJsonContract,
  PersonContract,
)
from _p3_40_contract_5d_fixtures import (  # noqa: E402
  valid_inferred_role_dict,
  valid_people_json_dict,
  valid_person_dict,
)


# ---------------------------------------------------------------------------
# PersonContract (9 fields)
# ---------------------------------------------------------------------------

class PersonContractTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = PersonContract.model_validate(valid_person_dict())
    self.assertEqual(contract.full_name, "Jane Doe")

  def test_missing_required_field_rejected(self) -> None:
    """Pick one of the 8 non-nullable required fields."""
    payload = valid_person_dict()
    del payload["full_name"]
    with self.assertRaises(ValidationError) as ctx:
      PersonContract.model_validate(payload)
    self.assertIn("full_name", str(ctx.exception))

  def test_annual_wage_accepts_none(self) -> None:
    contract = PersonContract.model_validate(
      valid_person_dict(annual_wage=None)
    )
    self.assertIsNone(contract.annual_wage)

  def test_annual_wage_accepts_zero_and_negative(self) -> None:
    """Per §0 / F4: numeric range NOT enforced."""
    zero_contract = PersonContract.model_validate(
      valid_person_dict(annual_wage=0.0)
    )
    negative_contract = PersonContract.model_validate(
      valid_person_dict(annual_wage=-1000.0)
    )
    self.assertEqual(zero_contract.annual_wage, 0.0)
    self.assertEqual(negative_contract.annual_wage, -1000.0)

  def test_experience_years_free_form_string_accepted(self) -> None:
    """Per F8: schema types as string (NOT number). Free-form
    values like '10+ years', 'indefinite', '' all pass --
    NO int coercion, NO pattern matching."""
    for value in ("10+ years", "indefinite", "", "0.5 years", "decades"):
      contract = PersonContract.model_validate(
        valid_person_dict(experience_years=value)
      )
      self.assertEqual(contract.experience_years, value)

  def test_wage_source_accepts_non_vocabulary_string(self) -> None:
    """Per §0 / F9: wage_source vocabulary
    (client_override / gpt_estimate / unknown) documented at
    consultant.py:218-221 but NOT in schema enum -- bare str
    accepts any string."""
    contract = PersonContract.model_validate(
      valid_person_dict(wage_source="custom-source-v2")
    )
    self.assertEqual(contract.wage_source, "custom-source-v2")

  def test_legacy_fallback_fields_ignored(self) -> None:
    """F2: PersonContract extra='ignore' accepts legacy
    fallback person-item fields (role / name /
    months_until_hire) that post_intake_headcount/schedule.py:
    693-706 defensively reads. Not in the GPT schema; not
    typed on PersonContract."""
    payload = valid_person_dict()
    payload["role"] = "legacy-role-key"
    payload["name"] = "legacy-name-key"
    payload["months_until_hire"] = 12.0  # wrong-sub-contract leak
    contract = PersonContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "role"))
    self.assertFalse(hasattr(contract, "name"))
    self.assertFalse(hasattr(contract, "months_until_hire"))


# ---------------------------------------------------------------------------
# InferredRoleContract (5 fields)
# ---------------------------------------------------------------------------

class InferredRoleContractTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    contract = InferredRoleContract.model_validate(
      valid_inferred_role_dict()
    )
    self.assertEqual(contract.role_title, "Store Manager")

  def test_missing_required_field_rejected(self) -> None:
    payload = valid_inferred_role_dict()
    del payload["notes"]
    with self.assertRaises(ValidationError):
      InferredRoleContract.model_validate(payload)

  def test_annual_wage_and_months_until_hire_accept_none(self) -> None:
    contract = InferredRoleContract.model_validate(
      valid_inferred_role_dict(annual_wage=None, months_until_hire=None)
    )
    self.assertIsNone(contract.annual_wage)
    self.assertIsNone(contract.months_until_hire)

  def test_months_until_hire_negative_accepted(self) -> None:
    """Per §0 / F4: months_until_hire range NOT enforced."""
    contract = InferredRoleContract.model_validate(
      valid_inferred_role_dict(months_until_hire=-3.0)
    )
    self.assertEqual(contract.months_until_hire, -3.0)


# ---------------------------------------------------------------------------
# PeopleJsonContract (6 typed top-level fields)
# ---------------------------------------------------------------------------

class PeopleJsonContractTest(unittest.TestCase):

  def test_valid_production_post_pop_payload_accepted(self) -> None:
    """Default fixture matches production POST-POP shape per
    F1 / T3: key_people_summary OMITTED (popped at
    intake_consult.py:6241)."""
    contract = PeopleJsonContract.model_validate(
      valid_people_json_dict()
    )
    self.assertEqual(len(contract.people), 1)
    self.assertEqual(len(contract.inferred_roles), 1)
    self.assertIsNone(contract.key_people_summary)
    self.assertEqual(contract.business_naics_6, "722515")

  def test_valid_payload_with_key_people_summary_accepted(self) -> None:
    """F1 / PSL2: contract accepts BOTH presence and absence
    of key_people_summary. This verifies the present case
    (which would only occur in pre-pop in-memory state, never
    in persisted drafts -- but the contract still accepts it
    for robustness)."""
    contract = PeopleJsonContract.model_validate(
      valid_people_json_dict(include_key_people_summary=True)
    )
    self.assertIn("Jane Doe", contract.key_people_summary)

  def test_key_people_summary_accepts_explicit_none(self) -> None:
    """F1: Optional[str] = None accepts explicit None."""
    payload = valid_people_json_dict(include_key_people_summary=True)
    payload["key_people_summary"] = None
    contract = PeopleJsonContract.model_validate(payload)
    self.assertIsNone(contract.key_people_summary)

  def test_missing_always_present_field_rejected(self) -> None:
    """4 always-present fields: people, inferred_roles,
    inferred_roles_summary, confidence. Pick one."""
    payload = valid_people_json_dict()
    del payload["inferred_roles_summary"]
    with self.assertRaises(ValidationError) as ctx:
      PeopleJsonContract.model_validate(payload)
    self.assertIn("inferred_roles_summary", str(ctx.exception))

  def test_empty_people_list_accepted(self) -> None:
    """Per §0 / F4: schema people.minItems=1 NOT enforced."""
    contract = PeopleJsonContract.model_validate(
      valid_people_json_dict(people=[])
    )
    self.assertEqual(contract.people, [])

  def test_empty_inferred_roles_list_accepted(self) -> None:
    """Per §0 / F4: schema inferred_roles.minItems=1 NOT
    enforced."""
    contract = PeopleJsonContract.model_validate(
      valid_people_json_dict(inferred_roles=[])
    )
    self.assertEqual(contract.inferred_roles, [])

  def test_business_naics_6_accepts_none(self) -> None:
    """F7: Optional[str] = None accepts explicit None."""
    payload = valid_people_json_dict()
    payload["business_naics_6"] = None
    contract = PeopleJsonContract.model_validate(payload)
    self.assertIsNone(contract.business_naics_6)

  def test_business_naics_6_accepts_absent(self) -> None:
    """F7: legacy-draft safety. Key entirely absent (defaults
    to None)."""
    contract = PeopleJsonContract.model_validate(
      valid_people_json_dict(include_business_naics_6=False)
    )
    self.assertIsNone(contract.business_naics_6)

  def test_extra_keys_ignored(self) -> None:
    """F3: extra='ignore' on top-level. Future schema-version
    drift tolerated."""
    payload = valid_people_json_dict()
    payload["future_field_v2"] = "tolerated"
    contract = PeopleJsonContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "future_field_v2"))

  def test_nested_person_validation_propagates(self) -> None:
    """Invalid nested PersonContract field surfaces at the
    top-level validation."""
    payload = valid_people_json_dict()
    del payload["people"][0]["full_name"]
    with self.assertRaises(ValidationError) as ctx:
      PeopleJsonContract.model_validate(payload)
    self.assertIn("full_name", str(ctx.exception))

  def test_nested_inferred_role_validation_propagates(self) -> None:
    payload = valid_people_json_dict()
    del payload["inferred_roles"][0]["role_title"]
    with self.assertRaises(ValidationError) as ctx:
      PeopleJsonContract.model_validate(payload)
    self.assertIn("role_title", str(ctx.exception))

  def test_wrong_outer_json_type_for_people_rejected(self) -> None:
    """people is List[PersonContract]. A string is NOT a list
    -- structural type mismatch is THE thing the contract
    fires on per §0."""
    payload = valid_people_json_dict()
    payload["people"] = "Jane Doe"  # string, not list
    with self.assertRaises(ValidationError):
      PeopleJsonContract.model_validate(payload)


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

class ModuleConstantsTest(unittest.TestCase):

  def test_stage_label_value_pinned(self) -> None:
    self.assertEqual(
      PEOPLE_JSON_STAGE_LABEL, "INTAKE_DRAFT::people_json",
    )

  def test_top_level_contract_has_6_typed_fields(self) -> None:
    """4 always-present + 1 nullable-required Optional + 1
    production-popped Optional = 6. Pins the field set."""
    self.assertEqual(len(PeopleJsonContract.model_fields), 6)


if __name__ == "__main__":
  unittest.main()
