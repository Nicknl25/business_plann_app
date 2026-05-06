"""Module 4 — table migration tests.

Verifies the four migration targets:

  Task 4.1/4.2 — cash policy preferred-ratio columns + cash runner reads them
  Task 4.3 — convergence guard columns on `post_intake_process_sequence_lookup`
             + the runner reads via `_convergence_guard_float/_int`
  Task 4.4/4.5 — `post_intake_planning_mode_policy_lookup` table + 3 default
                 rows + `stage_planning_ramp_policy` reads from it
  Task 4.6 — maintenance_capex prose hardcode deleted + NAICS-bound contract
             row enforces the bound

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module4_table_migrations.py"`
"""

from __future__ import annotations

import inspect
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_mapping import (  # noqa: E402
  load_post_intake_cash_policy_rows,
  load_post_intake_planning_mode_policy_rows,
  post_intake_cash_policy_for,
  post_intake_planning_mode_policy_for,
  stage_planning_ramp_policy,
)
from client_intake_and_finmo.post_intake_cash import runner as _cash_runner  # noqa: E402
from client_intake_and_finmo.post_intake_convergence import runner as _conv_runner  # noqa: E402
from client_intake_and_finmo.post_intake_contracts import runner as _contracts_runner  # noqa: E402


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
# Task 4.1 / 4.2 — cash policy preferred ratios.
# --------------------------------------------------------------------------


def test_cash_policy_rows_carry_preferred_ratio_columns() -> None:
  rows = load_post_intake_cash_policy_rows()
  assert rows, "cash policy table empty"
  for r in rows:
    for key in (
      "preferred_debt_to_assets_ratio",
      "preferred_equity_to_assets_ratio",
      "preferred_distribution_yield_target",
      "preferred_min_cash_runway_months",
    ):
      assert key in r, f"row missing {key}: {r}"


def test_cash_policy_defaults_match_legacy_constants() -> None:
  rows = load_post_intake_cash_policy_rows()
  for r in rows:
    assert abs(r["preferred_debt_to_assets_ratio"] - 0.40) < 1e-6, r
    assert abs(r["preferred_equity_to_assets_ratio"] - 0.60) < 1e-6, r


def test_cash_runner_legacy_constants_deleted() -> None:
  assert not hasattr(_cash_runner, "_CASH_STRATEGY_PREFERRED_DEBT_RATIO"), (
    "Module 4 Task 4.2: legacy _CASH_STRATEGY_PREFERRED_DEBT_RATIO constant should be deleted"
  )
  assert not hasattr(_cash_runner, "_CASH_STRATEGY_PREFERRED_EQUITY_RATIO"), (
    "Module 4 Task 4.2: legacy _CASH_STRATEGY_PREFERRED_EQUITY_RATIO constant should be deleted"
  )


def test_cash_runner_helper_returns_policy_row_values() -> None:
  debt, equity = _cash_runner._preferred_capital_ratios_for(
    selected_cash_strategy="balanced",
    debt_position_override="healthy_debt",
  )
  # Must equal the policy row defaults (0.40 / 0.60).
  assert abs(debt - 0.40) < 1e-6, debt
  assert abs(equity - 0.60) < 1e-6, equity


def test_cash_runner_helper_raises_on_missing_strategy() -> None:
  raised = False
  try:
    _cash_runner._preferred_capital_ratios_for(
      selected_cash_strategy="",
      debt_position_override="healthy_debt",
    )
  except RuntimeError as exc:
    raised = True
    assert "missing_strategy" in str(exc), str(exc)
  assert raised, "expected RuntimeError when cash_strategy is empty"


# --------------------------------------------------------------------------
# Task 4.3 — convergence guard columns.
# --------------------------------------------------------------------------


def test_convergence_guard_legacy_constants_deleted() -> None:
  for legacy in (
    "_CYCLE_DEADLINE_GUARD_SECONDS",
    "_PLANNER_GPT_MAX_SECONDS",
    "_VERIFICATION_GPT_MAX_SECONDS",
    "_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT",
    "_CONVERGENCE_TOTAL_PHASE_BUDGET_SECONDS",
  ):
    assert not hasattr(_conv_runner, legacy), (
      f"Module 4 Task 4.3: legacy constant {legacy} should be deleted; values now live on the sequence row"
    )


def test_convergence_guard_helpers_match_pre_v4_values() -> None:
  assert _conv_runner._convergence_guard_float("cycle_deadline_guard_seconds") == 8.0
  assert _conv_runner._convergence_guard_float("planner_gpt_max_seconds") == 150.0
  assert _conv_runner._convergence_guard_float("verification_gpt_max_seconds") == 45.0
  assert _conv_runner._convergence_guard_float("total_phase_budget_seconds") == 720.0
  assert _conv_runner._convergence_guard_int("non_productive_cycle_limit") == 3


def test_convergence_guard_helper_raises_on_unknown_field() -> None:
  raised = False
  try:
    _conv_runner._convergence_guard_float("not_a_real_field")
  except RuntimeError as exc:
    raised = True
    assert "unknown_guard_field" in str(exc), str(exc)
  assert raised, "expected unknown-field guard"


# --------------------------------------------------------------------------
# Task 4.4 / 4.5 — planning mode policy table.
# --------------------------------------------------------------------------


def test_planning_mode_policy_table_has_three_default_rows() -> None:
  rows = load_post_intake_planning_mode_policy_rows()
  modes = {r["planning_mode"] for r in rows}
  for required in ("rebalance", "turnaround", "normalize"):
    assert required in modes, f"missing planning_mode {required}: {modes}"


def test_planning_mode_policy_for_returns_expected_values() -> None:
  rebalance = post_intake_planning_mode_policy_for("rebalance")
  assert rebalance is not None
  assert rebalance["profitability_floor_q1_q4"] == 0.0
  assert rebalance["profitability_floor_q5_q10"] == 0.02
  assert rebalance["operational_distress_allows_early_losses"] is False
  assert rebalance["operational_requires_nonnegative_from_q1"] is True
  assert rebalance["loss_allowed_latest_quarter"] is None

  turnaround = post_intake_planning_mode_policy_for("turnaround")
  assert turnaround is not None
  assert turnaround["operational_distress_allows_early_losses"] is True
  assert turnaround["operational_requires_nonnegative_from_q1"] is False
  # Pre-v4 turnaround/operational did NOT set loss_allowed_latest_quarter
  # for non-early stages — the table preserves that by setting it to NULL.
  assert turnaround["loss_allowed_latest_quarter"] is None


def test_stage_planning_ramp_policy_rebalance_operational_matches_pre_v4() -> None:
  policy = stage_planning_ramp_policy(
    stage_family="operational",
    planning_mode="rebalance",
  )
  vr = policy["validator_rules"]
  assert vr.get("operational_requires_nonnegative_from_q1") is True
  assert vr.get("operational_requires_positive_from_q5") is True
  assert vr.get("q1_to_q20_min_net_income_margin_floor") == 0.0
  assert vr.get("q5_to_q20_min_net_income_margin_floor") == 0.02
  assert "operational_distress_allows_early_losses" not in vr


def test_stage_planning_ramp_policy_turnaround_operational_matches_pre_v4() -> None:
  policy = stage_planning_ramp_policy(
    stage_family="operational",
    planning_mode="turnaround",
  )
  vr = policy["validator_rules"]
  assert vr.get("operational_distress_allows_early_losses") is True
  # Pre-v4 distress branch did NOT set the operational floors.
  assert vr.get("q1_to_q20_min_net_income_margin_floor") is None
  assert vr.get("q5_to_q20_min_net_income_margin_floor") is None
  assert vr.get("operational_requires_nonnegative_from_q1") is None
  assert vr.get("operational_requires_positive_from_q5") is None


def test_stage_planning_ramp_policy_early_loss_allowed_universal() -> None:
  # Early stage sets loss_allowed_latest_quarter=8 regardless of planning_mode
  # (preserved exactly from pre-v4 behavior).
  for mode in ("rebalance", "turnaround", "normalize"):
    policy = stage_planning_ramp_policy(stage_family="early", planning_mode=mode)
    assert policy["validator_rules"].get("loss_allowed_latest_quarter") == 8, (mode, policy)


def test_stage_planning_ramp_policy_exposes_planning_mode_source() -> None:
  policy = stage_planning_ramp_policy(stage_family="operational", planning_mode="rebalance")
  source = policy.get("planning_mode_policy_source")
  assert isinstance(source, dict), policy
  assert source.get("planning_mode") == "rebalance"
  assert source.get("table") == "post_intake_planning_mode_policy_lookup"


# --------------------------------------------------------------------------
# Task 4.6 — maintenance_capex prose hardcode deleted.
# --------------------------------------------------------------------------


def test_maintenance_capex_prose_bound_deleted() -> None:
  src = inspect.getsource(_contracts_runner)
  # The hardcoded prose "must be at least 2 and no more than 15" was the
  # legacy universal-business bound. v4 deletes both the prompt-prose
  # version (in hard_rules) and the post-validation < 2.0 / > 15.0 check.
  # Allow `# DELETED` comments to mention the removed text.
  meaningful_lines = [
    line for line in src.splitlines()
    if "must be at least 2 and no more than 15" in line
    and not line.strip().startswith("#")
  ]
  assert not meaningful_lines, (
    f"Module 4 Task 4.6: hardcoded prose still present in non-comment lines:\n  "
    + "\n  ".join(meaningful_lines)
  )


def test_maintenance_capex_post_validation_uses_schema_bounds() -> None:
  src = inspect.getsource(_contracts_runner)
  # The legacy `< 2.0 or > 15.0` post-validation check was deleted; the
  # NAICS-bound contract row now enforces bounds at the OpenAI schema
  # layer. v4 keeps a minimal sanity check that the value is positive.
  assert "< 2.0 or maintenance_capex_percent > 15.0" not in src, (
    "Module 4 Task 4.6: legacy < 2.0 or > 15.0 post-validation should be deleted"
  )


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_module4_table_migrations.py")
  print("-" * 70)
  tests = [
    ("cash_policy_rows_have_preferred_ratio_columns", test_cash_policy_rows_carry_preferred_ratio_columns),
    ("cash_policy_defaults_match_legacy", test_cash_policy_defaults_match_legacy_constants),
    ("cash_runner_legacy_constants_deleted", test_cash_runner_legacy_constants_deleted),
    ("cash_runner_helper_returns_policy_values", test_cash_runner_helper_returns_policy_row_values),
    ("cash_runner_helper_raises_missing_strategy", test_cash_runner_helper_raises_on_missing_strategy),
    ("convergence_legacy_constants_deleted", test_convergence_guard_legacy_constants_deleted),
    ("convergence_guards_match_pre_v4", test_convergence_guard_helpers_match_pre_v4_values),
    ("convergence_guard_unknown_field_raises", test_convergence_guard_helper_raises_on_unknown_field),
    ("planning_mode_three_default_rows", test_planning_mode_policy_table_has_three_default_rows),
    ("planning_mode_policy_returns_expected", test_planning_mode_policy_for_returns_expected_values),
    ("stage_ramp_rebalance_operational_pre_v4", test_stage_planning_ramp_policy_rebalance_operational_matches_pre_v4),
    ("stage_ramp_turnaround_operational_pre_v4", test_stage_planning_ramp_policy_turnaround_operational_matches_pre_v4),
    ("stage_ramp_early_loss_allowed_universal", test_stage_planning_ramp_policy_early_loss_allowed_universal),
    ("stage_ramp_exposes_planning_mode_source", test_stage_planning_ramp_policy_exposes_planning_mode_source),
    ("maintenance_capex_prose_deleted", test_maintenance_capex_prose_bound_deleted),
    ("maintenance_capex_post_validation_uses_schema", test_maintenance_capex_post_validation_uses_schema_bounds),
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
