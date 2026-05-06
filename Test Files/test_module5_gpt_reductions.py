"""Module 5 tests — GPT reductions.

Covers:
  Task 5.1 — `maintenance_capex_percent` GPT call DELETED, replaced with
             deterministic NAICS-cascade lookup.
  Task 5.2 — `r_and_d_applicability` GPT call short-circuited via NAICS-2
             lookup table for unambiguous sectors; GPT remains tiebreaker
             for `optional` sectors.
  Task 5.4 — convergence direct-fit short-circuit verified (already wired
             in Module 2 Task 2.4; this test just confirms the wiring is
             still in place after Module 5 changes).

Tasks 5.3 (balance_sheet_contextual_seed), 5.5 (cash_strategy_review
allocator), and 5.6 (verification GPT deletion) are intentionally NOT
covered here — those tasks were DEFERRED with concrete reasoning per the
session's "don't break realism" directive. See module 5 notes for details.

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
