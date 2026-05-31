"""P3.41 NexGen E2E iter 7 — regression tests for the two round-1
set-tool source defects.

Surfaced when iters 1-6 unblocked the path through to the round-1
amalgamated set-tool boundary. Both pre-existing latent defects in
never-clean-E2E code:

Bug 1 — TypeError. The maintenance-capex caller path in
``post_intake_amalgamated/tools/set_capex_rd_balance_seed.py:235-239``
was spreading ``**builder_inputs`` (which carries 6 keys) into
``_derive_maintenance_capex_percent_from_naics`` (which accepts only
4 keyword-only params). The extra ``model_input_json`` key tripped
``TypeError: got an unexpected keyword argument``. Fixed to explicit
kwargs matching the R&D sibling's pattern.

Bug 2 — NameError. ``_slim_balance_sheet_seed_proposal_for_contract``
in ``post_intake_contracts/runner.py:1516`` referenced a module-level
constant ``_BALANCE_SHEET_SEED_CONTRACT_ROW_FIELDS`` that was never
defined anywhere in the codebase. Fixed by deriving the whitelist
from the authoritative ``balance_sheet_contextual_seed`` contract
schema via ``_balance_sheet_seed_contract_row_fields()`` (cached at
the function-attribute level) -- single-source-of-truth pattern.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# ---------------------------------------------------------------------------
# Bug 1 — maintenance-capex caller no longer trips TypeError on the
# realistic builder_inputs bag (which carries model_input_json + finmo_json
# alongside the 4 fields the callee accepts).
# ---------------------------------------------------------------------------

class MaintenanceCapexCallerKwargsTest(unittest.TestCase):

  def test_maintenance_capex_runs_with_full_builder_inputs(self) -> None:
    """The caller is reached with builder_inputs containing all 6 keys
    set_capex_rd_balance_seed assembles (business_facts, ops_json,
    financials_json, financials_year1_json, model_input_json,
    finmo_json). The previous **spread tripped TypeError because the
    callee declares only 4 keyword-only params. The explicit-kwargs
    fix must accept this bag and return the maintenance_rate payload
    shape (the callee falls back to the conservative default when
    NAICS / financials are empty, so an empty bag still returns a
    well-shaped dict)."""
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E501
      _maintenance_capex,
    )
    builder_inputs = {
      "business_facts": {},
      "ops_json": {},
      "financials_json": {},
      "financials_year1_json": {},
      "model_input_json": {"finmo_path": ""},
      "finmo_json": {"quarter_rows": []},
    }
    payload = _maintenance_capex(builder_inputs)
    self.assertIsInstance(payload, dict)
    self.assertIn("maintenance_capex_percent", payload)
    self.assertIn("decision_source", payload)


# ---------------------------------------------------------------------------
# Bug 2 — derived contract-row whitelist:
#   (a) the slimmer runs without NameError
#   (b) the derived field set matches the balance_sheet_contextual_seed
#       contract schema's grid-row properties (parity guard against drift)
#   (c) metadata fields the proposer attaches are excluded by the derivation
# ---------------------------------------------------------------------------

class BalanceSheetSeedContractRowFieldsTest(unittest.TestCase):

  def test_derivation_matches_schema_grid_row_properties(self) -> None:
    """Parity guard: the derived whitelist must equal the schema's
    grid-row properties. If the schema gains/loses a property and
    the derivation logic still walks the same path, the two stay in
    sync automatically. If the schema-path changes, this test fails
    loudly and points to where the derivation needs updating."""
    from client_intake_and_finmo.post_intake_contracts.runner import (
      _balance_sheet_contextual_seed_schema,
      _balance_sheet_seed_contract_row_fields,
    )
    schema = _balance_sheet_contextual_seed_schema()
    grid = schema.get("properties", {}).get("balance_sheet_seed_grid", {})
    items = grid.get("items", {}) if isinstance(grid, dict) else {}
    schema_properties = (
      set(items.get("properties", {}).keys())
      if isinstance(items, dict)
      else set()
    )
    derived = set(_balance_sheet_seed_contract_row_fields())
    self.assertEqual(
      derived, schema_properties,
      "derived whitelist must equal schema grid-row properties",
    )

  def test_metadata_fields_excluded_from_derivation(self) -> None:
    """The four proposer-metadata fields (naics_provenance,
    decision_source, naics_6, source_of_truth) must NOT appear in the
    derived whitelist -- they're stripped pre-validation and
    re-attached post-validation."""
    from client_intake_and_finmo.post_intake_contracts.runner import (
      _balance_sheet_seed_contract_row_fields,
    )
    metadata_fields = {
      "naics_provenance",
      "decision_source",
      "naics_6",
      "source_of_truth",
    }
    derived = set(_balance_sheet_seed_contract_row_fields())
    leaked = metadata_fields & derived
    self.assertFalse(
      leaked,
      f"metadata fields leaked into contract-row whitelist: {leaked}",
    )

  def test_slimmer_runs_without_nameerror_and_keeps_only_whitelist(
    self,
  ) -> None:
    """Bug 2 fix: the slimmer used to raise NameError because of an
    undefined module-level constant. It must now run cleanly and
    produce rows whose keys equal the derived whitelist (no
    metadata)."""
    from client_intake_and_finmo.post_intake_contracts.runner import (
      _balance_sheet_seed_contract_row_fields,
      _slim_balance_sheet_seed_proposal_for_contract,
    )
    proposal = {
      "balance_sheet_seed_grid": [
        {
          "lever_id": "balance_sheet::Owner's Capital",
          "applicable": True,
          "seed_value": 100.0,
          "value_kind": "currency",
          "rationale": "smoke",
          # The 4 metadata fields the proposer attaches:
          "naics_provenance": {"foo": 1},
          "decision_source": "python_deterministic",
          "naics_6": "513210",
          "source_of_truth": "python_proposer",
        },
      ],
      "rationale": "smoke rationale long enough to satisfy validator",
    }
    slim = _slim_balance_sheet_seed_proposal_for_contract(proposal)
    self.assertIn("balance_sheet_seed_grid", slim)
    self.assertEqual(len(slim["balance_sheet_seed_grid"]), 1)
    slim_keys = set(slim["balance_sheet_seed_grid"][0].keys())
    self.assertEqual(
      slim_keys, set(_balance_sheet_seed_contract_row_fields()),
      "slimmed row keys must equal the derived contract-row whitelist",
    )

  def test_cache_returns_same_tuple_object(self) -> None:
    """The derivation is cached on the function attribute. Repeated
    calls must return the same tuple object (zero re-derivation
    work on the hot path -- _slim runs per row)."""
    from client_intake_and_finmo.post_intake_contracts.runner import (
      _balance_sheet_seed_contract_row_fields,
    )
    first = _balance_sheet_seed_contract_row_fields()
    second = _balance_sheet_seed_contract_row_fields()
    self.assertIs(first, second)


if __name__ == "__main__":
  unittest.main()
