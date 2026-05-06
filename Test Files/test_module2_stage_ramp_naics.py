"""Module 2 Stage A + Stage C verification.

Stage A (Task 2.2) — verify the total-phase budget constant is in place.
Stage C (Task 2.6) — verify `stage_planning_ramp_policy` attaches NAICS qoq
metadata when `business_naics` is supplied, AND remains backward-compatible
when it is not.

Tasks 2.1 (DDL move), 2.3 (oscillation hash), 2.7 (three new validators), and
2.8 (sequence sub-steps) are documented as deferred in
context/post_intake_module_2_convergence_determinism.md notes.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module2_stage_ramp_naics.py"`
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

from client_intake_and_finmo.post_intake_convergence import runner as _runner  # noqa: E402
from client_intake_and_finmo.post_intake_mapping import stage_planning_ramp_policy  # noqa: E402


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
# Stage A — Task 2.2.
# --------------------------------------------------------------------------


def test_total_phase_budget_constant_exists() -> None:
  assert hasattr(_runner, "_CONVERGENCE_TOTAL_PHASE_BUDGET_SECONDS"), (
    "module 2 task 2.2: total-phase budget constant missing"
  )
  budget = float(_runner._CONVERGENCE_TOTAL_PHASE_BUDGET_SECONDS)
  # 720s (12 min) is the chosen value per spec — sanity-check it is in a
  # reasonable range so a future bad edit (e.g., set to 0) is caught.
  assert 240.0 <= budget <= 1800.0, f"unexpected budget value {budget}"


def test_total_phase_budget_is_used_in_loop() -> None:
  # Read the source of `_run_unified_convergence_phase` and confirm the
  # budget guard is wired up. We don't run the loop end-to-end here.
  import inspect
  for name, member in inspect.getmembers(_runner):
    if not callable(member) or not getattr(member, "__module__", "").endswith("runner"):
      continue
    try:
      src = inspect.getsource(member)
    except Exception:
      continue
    if "_CONVERGENCE_TOTAL_PHASE_BUDGET_SECONDS" in src and "convergence_total_phase_budget_exceeded" in src:
      return  # found a function that wires the guard
  raise AssertionError(
    "no function in runner.py references both the budget constant and the "
    "fail-fast detail string `convergence_total_phase_budget_exceeded`"
  )


# --------------------------------------------------------------------------
# Stage C — Task 2.6.
# --------------------------------------------------------------------------


def test_stage_ramp_policy_backward_compat_no_naics() -> None:
  policy = stage_planning_ramp_policy(stage_family="startup", planning_mode="rebalance")
  # Must still expose the existing fields and ceilings.
  assert policy.get("policy_version") == "stage_planning_ramp_policy_v1"
  assert policy.get("stage_family") == "startup"
  ceilings = policy.get("early_revenue_share_ceiling_of_late_run_rate") or {}
  assert ceilings.get("Q1") == 0.25, ceilings
  assert ceilings.get("Q4") == 0.80, ceilings
  # NAICS metadata fields exist but are None.
  assert policy.get("naics_qoq_metric_key") == "startup_qoq_growth_typical"
  assert policy.get("naics_level_used") is None
  assert policy.get("confidence_tier_used") is None
  assert policy.get("qoq_growth_band") is None


def test_stage_ramp_policy_with_naics_attaches_qoq_metadata() -> None:
  policy = stage_planning_ramp_policy(
    stage_family="startup",
    planning_mode="rebalance",
    business_naics="455211",
  )
  # The hardcoded ceilings remain untouched (Stage C v1 — Module 2 spec
  # actual ceiling replacement deferred to a focused follow-up).
  ceilings = policy.get("early_revenue_share_ceiling_of_late_run_rate") or {}
  assert ceilings.get("Q1") == 0.25
  assert ceilings.get("Q4") == 0.80
  band = policy.get("qoq_growth_band")
  assert isinstance(band, dict), f"qoq_growth_band not attached: {band}"
  assert band.get("metric_key") == "startup_qoq_growth_typical"
  for key in ("benchmark_min", "benchmark_target", "benchmark_max"):
    assert key in band, f"qoq_growth_band missing {key}: {band}"
  assert policy.get("naics_level_used") is not None
  assert policy.get("confidence_tier_used") in (
    "high", "medium", "low", "generic_default"
  ), policy.get("confidence_tier_used")


def test_stage_ramp_policy_qoq_metric_key_per_family() -> None:
  for family, expected_metric in (
    ("startup", "startup_qoq_growth_typical"),
    ("early", "early_qoq_growth_typical"),
    ("operational", "mature_qoq_growth_typical"),
  ):
    policy = stage_planning_ramp_policy(
      stage_family=family, planning_mode="rebalance"
    )
    assert policy.get("naics_qoq_metric_key") == expected_metric, (
      family, policy.get("naics_qoq_metric_key")
    )


def test_stage_ramp_policy_handles_invalid_naics_gracefully() -> None:
  # Empty string and None must not crash; metadata stays None.
  for naics in ("", None):
    policy = stage_planning_ramp_policy(
      stage_family="startup",
      planning_mode="rebalance",
      business_naics=naics,
    )
    assert policy.get("qoq_growth_band") is None, (naics, policy.get("qoq_growth_band"))
  # Garbage with no digits ("abc") falls through the cascade to the L0
  # generic_default — the resolver's documented degradation path. Acceptable
  # because the universal default is still real industry-typical data.
  policy_abc = stage_planning_ramp_policy(
    stage_family="startup",
    planning_mode="rebalance",
    business_naics="abc",
  )
  band = policy_abc.get("qoq_growth_band")
  assert isinstance(band, dict), band
  assert band.get("trust_flag") == "generic_default", band


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_module2_stage_ramp_naics.py")
  print("-" * 70)
  tests = [
    ("total_phase_budget_constant_exists", test_total_phase_budget_constant_exists),
    ("total_phase_budget_is_used_in_loop", test_total_phase_budget_is_used_in_loop),
    ("stage_ramp_policy_backward_compat_no_naics", test_stage_ramp_policy_backward_compat_no_naics),
    ("stage_ramp_policy_with_naics_attaches_qoq_metadata", test_stage_ramp_policy_with_naics_attaches_qoq_metadata),
    ("stage_ramp_policy_qoq_metric_key_per_family", test_stage_ramp_policy_qoq_metric_key_per_family),
    ("stage_ramp_policy_handles_invalid_naics_gracefully", test_stage_ramp_policy_handles_invalid_naics_gracefully),
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
