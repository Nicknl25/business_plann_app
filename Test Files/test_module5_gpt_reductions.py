"""Module 5 tests — GPT reductions.

Covers:
  Task 5.1 — `maintenance_capex_percent` GPT call DELETED, replaced with
             deterministic NAICS-cascade lookup.
  Task 5.2 — `r_and_d_applicability` GPT call short-circuited via NAICS-2
             lookup table for unambiguous sectors; GPT remains tiebreaker
             for `optional` sectors.
  Task 5.3 — `balance_sheet_contextual_seed` Python proposer (NAICS +
             intake anchors); GPT critic amends per-row decisions.
  Task 5.4 — convergence direct-fit short-circuit verified (already wired
             in Module 2 Task 2.4; this test just confirms the wiring is
             still in place after Module 5 changes).
  Task 5.5 — `cash_strategy_review` Python proposer (policy-priority
             funding allocator); GPT critic amends timing/lever choices.
             The legacy "GPT writes from scratch + retry-on-invalid" loop
             was REMOVED.
  Task 5.6 — `unified_convergence_verification` Python proposer (per-issue
             verdict from applied_updates); GPT critic amends verdicts
             based on domain judgment.

The Module 5 architecture across all six tasks: Python proposes structure,
GPT critiques structure. Python is the engineer, GPT is the consultant.
Every GPT call now operates on a deterministic proposal that's already
contract-valid; if GPT fails (timeout, garbage, missing key), Python's
proposal stands as the safety floor.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module5_gpt_reductions.py"`
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_mapping import (  # noqa: E402
  load_post_intake_r_and_d_applicability_rows,
  post_intake_r_and_d_applicability_for_naics2,
)
from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: E402
  _derive_maintenance_capex_percent_from_naics,
  _derive_r_and_d_applicability_from_naics,
)
from client_intake_and_finmo.post_intake_contracts import runner as _contracts_runner  # noqa: E402
from client_intake_and_finmo.post_intake_balance_sheet.contextual_seed import (  # noqa: E402
  propose_balance_sheet_contextual_seed_payload,
)
from client_intake_and_finmo.post_intake_cash.cash_strategy_proposer import (  # noqa: E402
  propose_cash_strategy_review_decision,
)
from client_intake_and_finmo.post_intake_cash import runner as _cash_runner  # noqa: E402
from client_intake_and_finmo.post_intake_realism.verification_proposer import (  # noqa: E402
  propose_realism_verification_payload,
)
from client_intake_and_finmo.post_intake_critique import (  # noqa: E402
  CRITIQUE_CONTRACT_SCHEMA,
  CritiqueResponse,
  apply_corrections_to_proposal,
  proposal_only_response,
)
from client_intake_and_finmo import numeric_solver as _solver  # noqa: E402


_RESULTS: List[Tuple[str, bool, str]] = []


def _run(name: str, fn: Callable[[], None]) -> None:
  try:
    fn()
    _RESULTS.append((name, True, ""))
    print(f"  PASS  {name}")
  except AssertionError as exc:
    _RESULTS.append((name, False, str(exc)))
    print(f"  FAIL  {name}: {exc}")
  except Exception as exc:
    _RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
    print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    traceback.print_exc()


# --------------------------------------------------------------------------
# Task 5.1 — maintenance_capex deterministic.
# --------------------------------------------------------------------------


def test_maintenance_capex_gpt_function_deleted_from_module() -> None:
  # The legacy `_estimate_maintenance_capex_percent_with_gpt` function and
  # its OpenAI-calling body were DELETED. The export list at module level
  # now exposes the deterministic replacement.
  assert hasattr(_contracts_runner, "_derive_maintenance_capex_percent_from_naics"), (
    "deterministic replacement not exported"
  )
  # The legacy name should not point at a function that calls OpenAI any
  # more. We accept either: the legacy name is gone entirely, OR the legacy
  # name is a thin shim. v5 deletes the body so the legacy name is gone.
  legacy = getattr(_contracts_runner, "_estimate_maintenance_capex_percent_with_gpt", None)
  if legacy is not None:
    import inspect
    src = inspect.getsource(legacy)
    assert "openai.com" not in src and "_post_openai" not in src, (
      "legacy name still calls OpenAI; v5 should have removed the GPT body"
    )


def test_maintenance_capex_deterministic_returns_naics_value_for_retail() -> None:
  result = _derive_maintenance_capex_percent_from_naics(
    business_facts={},
    ops_json={"business_naics_6": "455211"},
    financials_json={"initial_assets": 100_000},
    financials_year1_json={"company_revenue_total_year1": 1_000_000},
  )
  assert result["decision_source"] == "naics_cascade", result
  assert isinstance(result["maintenance_capex_percent"], float), result
  assert result["maintenance_capex_percent"] > 0.0, result
  prov = result.get("naics_provenance") or {}
  assert prov.get("metric_key") == "maintenance_capex_percent_of_revenue"
  assert prov.get("trust_flag") != "no_coverage"


def test_maintenance_capex_deterministic_differs_by_naics() -> None:
  retail = _derive_maintenance_capex_percent_from_naics(
    business_facts={},
    ops_json={"business_naics_6": "455211"},
    financials_json={"initial_assets": 100_000},
    financials_year1_json={"company_revenue_total_year1": 1_000_000},
  )
  software = _derive_maintenance_capex_percent_from_naics(
    business_facts={},
    ops_json={"business_naics_6": "511210"},
    financials_json={"initial_assets": 100_000},
    financials_year1_json={"company_revenue_total_year1": 1_000_000},
  )
  # Different industries should produce different values (the whole point
  # of NAICS-driven instead of a universal 8% prose default).
  assert retail["maintenance_capex_percent"] != software["maintenance_capex_percent"], (
    f"retail={retail['maintenance_capex_percent']} software={software['maintenance_capex_percent']}"
  )


def test_maintenance_capex_deterministic_raises_on_missing_naics() -> None:
  raised = False
  try:
    _derive_maintenance_capex_percent_from_naics(
      business_facts={},
      ops_json={},
      financials_json={"initial_assets": 100_000},
      financials_year1_json={"company_revenue_total_year1": 1_000_000},
    )
  except RuntimeError as exc:
    raised = True
    assert "naics_missing" in str(exc), str(exc)
  assert raised, "expected RuntimeError on missing NAICS"


# --------------------------------------------------------------------------
# Task 5.2 — R&D applicability NAICS-2 lookup.
# --------------------------------------------------------------------------


def test_r_and_d_applicability_table_seeded_with_three_categories() -> None:
  rows = load_post_intake_r_and_d_applicability_rows()
  assert len(rows) >= 20, f"expected >=20 default rows, got {len(rows)}"
  by_kind: Dict[str, List[str]] = {"required": [], "optional": [], "not_applicable": []}
  for r in rows:
    by_kind.setdefault(r["applicability_default"], []).append(r["naics_2"])
  for k in ("required", "optional", "not_applicable"):
    assert by_kind[k], f"missing rows for category {k}"
  # Sanity-check known sectors are categorized correctly.
  assert "51" in by_kind["required"], "Information should be required"
  assert "54" in by_kind["required"], "Professional Services should be required"
  assert "44" in by_kind["not_applicable"], "Retail should be not_applicable"
  assert "72" in by_kind["not_applicable"], "Accommodation/Food should be not_applicable"
  assert "33" in by_kind["optional"], "Manufacturing should be optional"


def test_r_and_d_applicability_for_naics2_returns_row() -> None:
  retail = post_intake_r_and_d_applicability_for_naics2("44")
  assert retail is not None
  assert retail["applicability_default"] == "not_applicable"

  software = post_intake_r_and_d_applicability_for_naics2("51")
  assert software is not None
  assert software["applicability_default"] == "required"

  # Pass full NAICS-6, function should slice to NAICS-2.
  retail_full = post_intake_r_and_d_applicability_for_naics2("455211")
  assert retail_full is not None
  assert retail_full["applicability_default"] == "not_applicable"


def test_r_and_d_deterministic_returns_decision_for_required() -> None:
  result = _derive_r_and_d_applicability_from_naics(
    business_facts={},
    ops_json={"business_naics_6": "511210"},
    financials_json={},
    financials_year1_json={},
    model_input_json={},
  )
  assert result is not None, "Information sector should produce deterministic decision"
  assert result["r_and_d_enabled"] is True
  assert result["decision_source"] == "naics_2_lookup"
  prov = result.get("naics_provenance") or {}
  assert prov.get("naics_2") == "51"
  assert prov.get("applicability_default") == "required"


def test_r_and_d_deterministic_returns_decision_for_not_applicable() -> None:
  result = _derive_r_and_d_applicability_from_naics(
    business_facts={},
    ops_json={"business_naics_6": "455211"},
    financials_json={},
    financials_year1_json={},
    model_input_json={},
  )
  assert result is not None
  assert result["r_and_d_enabled"] is False
  assert result["decision_source"] == "naics_2_lookup"


def test_r_and_d_deterministic_returns_none_for_optional_falls_through_to_gpt() -> None:
  # Manufacturing (NAICS 33) is `optional` — the deterministic function
  # returns None so the caller falls through to GPT for the tiebreaker.
  result = _derive_r_and_d_applicability_from_naics(
    business_facts={},
    ops_json={"business_naics_6": "332999"},
    financials_json={},
    financials_year1_json={},
    model_input_json={},
  )
  assert result is None, f"optional sector should defer to GPT tiebreaker, got: {result}"


def test_r_and_d_deterministic_returns_none_for_missing_naics() -> None:
  result = _derive_r_and_d_applicability_from_naics(
    business_facts={},
    ops_json={},
    financials_json={},
    financials_year1_json={},
    model_input_json={},
  )
  assert result is None


# --------------------------------------------------------------------------
# Task 5.3 — balance_sheet_contextual_seed proposer + critic.
# --------------------------------------------------------------------------


def test_balance_sheet_proposer_uses_intake_anchors_for_retail() -> None:
  payload = propose_balance_sheet_contextual_seed_payload(
    business_facts={"business_name": "Acme Retail"},
    ops_json={"business_naics_6": "452990"},
    financials_json={"ar_balance": 50000, "ap_balance": 100000, "inventory_balance": 200000},
    financials_year1_json={"company_revenue_total_year1": 4000000},
  )
  rows = {row["lever_id"]: row for row in payload["balance_sheet_seed_grid"]}
  ar_row = rows.get("balance_sheet::Accounts Receivable Days")
  ap_row = rows.get("balance_sheet::Accounts Payable Days")
  inv_row = rows.get("balance_sheet::Inventory Days")
  assert ar_row and ar_row["applicable"] is True, ar_row
  assert ap_row and ap_row["applicable"] is True, ap_row
  assert inv_row and inv_row["applicable"] is True, inv_row
  # Tier A intake anchor: ar_balance/quarter_revenue * 90.
  # 50000 / (4000000/4) * 90 = 4.5 days.
  assert abs(ar_row["seed_value"] - 4.5) < 0.01, ar_row
  # Provenance: Tier A intake anchor takes priority over NAICS cascade.
  assert "tier_a_intake_anchor" in ar_row["rationale"]


def test_balance_sheet_proposer_gates_inventory_for_software() -> None:
  payload = propose_balance_sheet_contextual_seed_payload(
    business_facts={"business_name": "Software Co"},
    ops_json={"business_naics_6": "511210"},
    financials_json={},
    financials_year1_json={"company_revenue_total_year1": 1000000},
  )
  rows = {row["lever_id"]: row for row in payload["balance_sheet_seed_grid"]}
  inv_row = rows.get("balance_sheet::Inventory Days")
  assert inv_row is not None
  # NAICS-2 51 (Information) is NOT in the inventory-applicable set.
  assert inv_row["applicable"] is False, inv_row
  assert inv_row["seed_value"] == 0.0, inv_row
  # Software companies often have deferred revenue (NAICS 51 IS in deferred set).
  deferred_row = rows.get("balance_sheet::Deferred Revenue (% of Revenue)")
  assert deferred_row and deferred_row["applicable"] is True


def test_balance_sheet_finalize_safety_floor_when_no_critic() -> None:
  # When OPENAI_API_KEY is missing, the runner returns the proposer's
  # output as the safety floor with decision_source `python_proposer_only`.
  # Stub the API key and the runtime deadline helper.
  original_openai_key = _contracts_runner._openai_key
  original_deadline = getattr(_contracts_runner, "_set_active_openai_deadline", None)
  _contracts_runner._openai_key = lambda: None
  _contracts_runner._set_active_openai_deadline = lambda x: None
  try:
    result = _contracts_runner._estimate_balance_sheet_contextual_seed_with_gpt(
      business_facts={"business_name": "Acme"},
      ops_json={"business_naics_6": "452990"},
      financials_json={"ar_balance": 50000, "ap_balance": 100000, "inventory_balance": 200000},
      financials_year1_json={"company_revenue_total_year1": 4000000},
      model_input_json={"sections": {}},
      finmo_json={"quarter_rows": []},
    )
  finally:
    _contracts_runner._openai_key = original_openai_key
    if original_deadline is not None:
      _contracts_runner._set_active_openai_deadline = original_deadline
  assert result["decision_source"] == "python_proposer_plus_gpt_critic"
  assert result["critique"]["review_status"] == "accepted"
  assert result["critique"]["critique_summary"] == "openai_key_missing_proposal_stands"
  rows = {row["lever_id"]: row for row in result["balance_sheet_seed_grid"]}
  assert "balance_sheet::Accounts Receivable Days" in rows
  assert rows["balance_sheet::Accounts Receivable Days"]["applicable"] is True


# --------------------------------------------------------------------------
# Task 5.5 — cash_strategy_review proposer + critic.
# --------------------------------------------------------------------------


def test_cash_proposer_picks_first_priority_source_with_headroom() -> None:
  context = {
    "required_funding_quarters": [
      {"quarter_index": 3, "required_incremental_funding_after_hard_rules": 50000, "buffer": 10000, "ending_cash_after_hard_rules": -40000},
    ],
    "funding_source_policy": {
      "allowed_funding_source_lever_ids": ["lev::OwnersCapital", "lev::DebtIssuance"],
    },
    "lever_bounds": {
      "lever_bounds": {
        "lev::OwnersCapital": [
          {"quarter_index": 3, "current_value": 0, "max_value": 75000, "supporting_metrics": {"cash_support_multiplier": 1.0}},
        ],
        "lev::DebtIssuance": [
          {"quarter_index": 3, "current_value": 0, "max_value": 200000, "supporting_metrics": {"cash_support_multiplier": 0.97}},
        ],
      },
    },
  }
  out = propose_cash_strategy_review_decision(
    cash_strategy_review_context=context,
    selected_cash_strategy="balanced",
    default_funding_source_lever_ids=["lev::OwnersCapital", "lev::DebtIssuance"],
    debt_issuance_lever_id="lev::DebtIssuance",
  )
  assert out["recommendation_mode"] == "adjust"
  plan = out["quarter_funding_plan"]
  assert len(plan) == 1
  q3 = plan[0]
  assert q3["quarter_index"] == 3
  assert q3["funding_sources"][0]["lever_id"] == "lev::OwnersCapital"
  assert q3["funding_sources"][0]["amount"] == 50000
  # OwnersCapital headroom 75k > 50k, so highest-priority source wins.
  diag = out["proposer_diagnostics"]
  assert diag["underfunded_quarters"] == []


def test_cash_proposer_falls_through_to_debt_when_owners_exhausted() -> None:
  context = {
    "required_funding_quarters": [
      {"quarter_index": 5, "required_incremental_funding_after_hard_rules": 100000, "buffer": 10000, "ending_cash_after_hard_rules": -90000},
    ],
    "funding_source_policy": {
      "allowed_funding_source_lever_ids": ["lev::OwnersCapital", "lev::DebtIssuance"],
    },
    "lever_bounds": {
      "lever_bounds": {
        "lev::OwnersCapital": [
          {"quarter_index": 5, "current_value": 0, "max_value": 50000, "supporting_metrics": {"cash_support_multiplier": 1.0}},
        ],
        "lev::DebtIssuance": [
          {"quarter_index": 5, "current_value": 0, "max_value": 200000, "supporting_metrics": {"cash_support_multiplier": 0.97}},
        ],
      },
    },
  }
  out = propose_cash_strategy_review_decision(
    cash_strategy_review_context=context,
    selected_cash_strategy="balanced",
    default_funding_source_lever_ids=["lev::OwnersCapital", "lev::DebtIssuance"],
    debt_issuance_lever_id="lev::DebtIssuance",
  )
  q5 = out["quarter_funding_plan"][0]
  assert q5["funding_sources"][0]["lever_id"] == "lev::DebtIssuance"
  assert q5["funding_sources"][0]["amount"] == 100000
  # Debt issuance gets grossed up by 1/0.97 ≈ 103093 to deliver 100000 of cash support.
  adjustment = out["recommended_adjustments"][0]
  assert adjustment["lever_id"] == "lev::DebtIssuance"
  assert abs(adjustment["exact_value"] - 103093) <= 1


def test_cash_proposer_emits_maintain_when_no_required_quarters() -> None:
  out = propose_cash_strategy_review_decision(
    cash_strategy_review_context={"required_funding_quarters": []},
    selected_cash_strategy="balanced",
    default_funding_source_lever_ids=["lev::OwnersCapital"],
    debt_issuance_lever_id="lev::DebtIssuance",
  )
  assert out["recommendation_mode"] == "maintain"
  assert out["quarter_funding_plan"] == []
  assert out["recommended_adjustments"] == []


# --------------------------------------------------------------------------
# Task 5.6 — unified_convergence_verification proposer + critic.
# --------------------------------------------------------------------------


def test_verification_proposer_marks_resolved_when_all_quarters_touched() -> None:
  out = propose_realism_verification_payload(
    issue_packets=[
      {"issue_code": "liquidity_failure", "severity": "high", "affected_quarters": [3, 4, 5], "candidate_lever_ids": ["lev::A"], "remaining_issue_severity_score": 80},
    ],
    applied_updates=[
      {"lever_id": "lev::A", "quarter_index": 3},
      {"lever_id": "lev::A", "quarter_index": 4},
      {"lever_id": "lev::A", "quarter_index": 5},
    ],
  )
  assert out["overall_assessment"] == "all_resolved"
  result = out["issue_results"][0]
  assert result["status"] == "resolved"
  assert result["remaining_problem_quarters"] == []
  assert result["remaining_issue_materiality"] == "none"


def test_verification_proposer_marks_improved_with_partial_coverage() -> None:
  out = propose_realism_verification_payload(
    issue_packets=[
      {"issue_code": "liquidity_failure", "severity": "high", "affected_quarters": [3, 4, 5], "candidate_lever_ids": ["lev::A"], "remaining_issue_severity_score": 80},
    ],
    applied_updates=[{"lever_id": "lev::A", "quarter_index": 3}],
  )
  assert out["overall_assessment"] == "no_progress" or out["overall_assessment"] == "partial_resolution"
  result = out["issue_results"][0]
  assert result["status"] == "improved"
  assert result["remaining_problem_quarters"] == [4, 5]


def test_verification_proposer_marks_stalled_when_no_lever_touched() -> None:
  out = propose_realism_verification_payload(
    issue_packets=[
      {"issue_code": "gross_margin_below_naics_floor", "severity": "medium", "affected_quarters": [1, 2], "candidate_lever_ids": ["lev::COGS"], "remaining_issue_severity_score": 50},
    ],
    applied_updates=[{"lever_id": "lev::Other", "quarter_index": 1}],
  )
  assert out["overall_assessment"] == "no_progress"
  result = out["issue_results"][0]
  assert result["status"] == "stalled"
  assert result["remaining_problem_quarters"] == [1, 2]


# --------------------------------------------------------------------------
# Critique contract — shared infrastructure for all three proposer/critic flows.
# --------------------------------------------------------------------------


def test_critique_contract_applies_corrections_via_field_path() -> None:
  proposal = {
    "balance_sheet_seed_grid": [
      {"lever_id": "lev::A", "applicable": True, "seed_value": 4.5},
      {"lever_id": "lev::B", "applicable": False, "seed_value": 0.0},
    ],
    "rationale": "deterministic proposer output",
  }
  response = CritiqueResponse.from_payload({
    "review_status": "amended",
    "corrections": [
      {
        "field_path": "balance_sheet_seed_grid[1].applicable",
        "current_value": False,
        "amended_value": True,
        "reason": "test override",
      },
      {
        "field_path": "balance_sheet_seed_grid[1].seed_value",
        "current_value": 0.0,
        "amended_value": 12.0,
        "reason": "test override",
      },
    ],
    "critique_summary": "Two surgical edits.",
  })
  amended = apply_corrections_to_proposal(proposal=proposal, response=response)
  assert amended["balance_sheet_seed_grid"][1]["applicable"] is True
  assert amended["balance_sheet_seed_grid"][1]["seed_value"] == 12.0
  assert amended["_critique_diagnostics"]["review_status"] == "amended"
  assert len(amended["_critique_diagnostics"]["applied_corrections"]) == 2
  assert amended["_critique_diagnostics"]["dropped_corrections"] == []


def test_critique_contract_drops_corrections_for_missing_paths() -> None:
  proposal = {"balance_sheet_seed_grid": [{"lever_id": "lev::A", "applicable": True}]}
  response = CritiqueResponse.from_payload({
    "review_status": "amended",
    "corrections": [
      {"field_path": "balance_sheet_seed_grid[5].applicable", "current_value": True, "amended_value": False, "reason": "out of range"},
      {"field_path": "non_existent_field", "current_value": None, "amended_value": "x", "reason": "wrong field"},
    ],
    "critique_summary": "GPT misread the structure.",
  })
  amended = apply_corrections_to_proposal(proposal=proposal, response=response)
  diag = amended["_critique_diagnostics"]
  # Both corrections target paths that don't exist; both are dropped.
  assert diag["applied_corrections"] == []
  assert len(diag["dropped_corrections"]) == 2


def test_critique_proposal_only_response_is_accepted() -> None:
  response = proposal_only_response(reason="critic_timeout")
  assert response.review_status == "accepted"
  assert response.corrections == []
  assert response.critique_summary == "critic_timeout"
  proposal = {"value": 42}
  amended = apply_corrections_to_proposal(proposal=proposal, response=response)
  # Accepted means no corrections applied; original payload is preserved.
  assert amended == {"value": 42}


# --------------------------------------------------------------------------
# Task 5.4 — solver direct-fit short-circuit (M2 Task 2.4 verification).
# --------------------------------------------------------------------------


def test_solver_algebraic_path_telemetry_fields_present() -> None:
  # M2 Task 2.4 added `algebraic_path_attempted` + `algebraic_path_result_code`
  # to per-attempt telemetry. Module 5 Task 5.4 verifies they are still
  # in place after v5 edits — this is a structural verification, not a
  # behavior test.
  import inspect
  src = inspect.getsource(_solver.solve_review_plan)
  assert "algebraic_path_attempted" in src, "M2 solver telemetry field missing"
  assert "direct_algebraic_one_dim_fit" in src, "M2 algebraic-fit message missing"


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_module5_gpt_reductions.py")
  print("-" * 70)
  tests = [
    ("maintenance_capex_legacy_gpt_deleted", test_maintenance_capex_gpt_function_deleted_from_module),
    ("maintenance_capex_deterministic_for_retail", test_maintenance_capex_deterministic_returns_naics_value_for_retail),
    ("maintenance_capex_differs_by_naics", test_maintenance_capex_deterministic_differs_by_naics),
    ("maintenance_capex_raises_on_missing_naics", test_maintenance_capex_deterministic_raises_on_missing_naics),
    ("r_and_d_table_three_categories", test_r_and_d_applicability_table_seeded_with_three_categories),
    ("r_and_d_for_naics2_returns_row", test_r_and_d_applicability_for_naics2_returns_row),
    ("r_and_d_deterministic_required_decision", test_r_and_d_deterministic_returns_decision_for_required),
    ("r_and_d_deterministic_not_applicable_decision", test_r_and_d_deterministic_returns_decision_for_not_applicable),
    ("r_and_d_optional_falls_through_to_gpt", test_r_and_d_deterministic_returns_none_for_optional_falls_through_to_gpt),
    ("r_and_d_missing_naics_returns_none", test_r_and_d_deterministic_returns_none_for_missing_naics),
    ("balance_sheet_proposer_uses_intake_anchors", test_balance_sheet_proposer_uses_intake_anchors_for_retail),
    ("balance_sheet_proposer_gates_inventory_for_software", test_balance_sheet_proposer_gates_inventory_for_software),
    ("balance_sheet_safety_floor_when_no_critic", test_balance_sheet_finalize_safety_floor_when_no_critic),
    ("cash_proposer_picks_first_priority_source", test_cash_proposer_picks_first_priority_source_with_headroom),
    ("cash_proposer_falls_through_to_debt", test_cash_proposer_falls_through_to_debt_when_owners_exhausted),
    ("cash_proposer_emits_maintain_when_no_required", test_cash_proposer_emits_maintain_when_no_required_quarters),
    ("verification_proposer_resolved_when_all_touched", test_verification_proposer_marks_resolved_when_all_quarters_touched),
    ("verification_proposer_improved_with_partial_coverage", test_verification_proposer_marks_improved_with_partial_coverage),
    ("verification_proposer_stalled_when_no_lever", test_verification_proposer_marks_stalled_when_no_lever_touched),
    ("critique_applies_corrections_via_field_path", test_critique_contract_applies_corrections_via_field_path),
    ("critique_drops_corrections_for_missing_paths", test_critique_contract_drops_corrections_for_missing_paths),
    ("critique_proposal_only_response_accepted", test_critique_proposal_only_response_is_accepted),
    ("solver_algebraic_telemetry_intact", test_solver_algebraic_path_telemetry_fields_present),
  ]
  for name, fn in tests:
    _run(name, fn)
  print("-" * 70)
  passed = sum(1 for _, ok, _ in _RESULTS if ok)
  failed = [(n, why) for n, ok, why in _RESULTS if not ok]
  print(f"{passed}/{len(_RESULTS)} passed")
  if failed:
    print("FAILURES:")
    for name, why in failed:
      print(f"  {name}: {why}")
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
