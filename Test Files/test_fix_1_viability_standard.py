"""Fix #1 — Viability Standard tests.

Built incrementally per the build order in
docs/architecture/fix_1_viability_standard_spec.md (@ 7e747a8).

Unit 1 (§5.1) — revenue_growth_q registered in the cohort resolver maps.
Unit 2 (§4.1) — age-derived 4-stage taxonomy.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_fix_1_viability_standard.py"`
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import date
from typing import Callable, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_solver import cohort_band_resolver as _cbr  # noqa: E402
from client_intake_and_finmo.post_intake_viability import stage as _stage  # noqa: E402


_RESULTS: List[Tuple[str, bool, str]] = []


def _run(name: str, fn: Callable[[], None]) -> None:
  try:
    fn()
    _RESULTS.append((name, True, ""))
  except Exception as exc:  # noqa: BLE001
    _RESULTS.append((name, False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))


# ---------------------------------------------------------------------------
# Unit 1 (§5.1) — register revenue_growth_q in the resolver.
# ---------------------------------------------------------------------------


def test_revenue_growth_q_in_known_columns() -> None:
  assert "revenue_growth_q" in _cbr._KNOWN_METRIC_COLUMNS, (
    "revenue_growth_q must be a known resolver column (§5.1)"
  )


def test_revenue_growth_metric_key_maps_to_column() -> None:
  assert _cbr.METRIC_KEY_TO_COLUMN.get("revenue_growth") == "revenue_growth_q"
  assert _cbr.METRIC_KEY_TO_COLUMN.get("revenue_growth_q") == "revenue_growth_q"


# ---------------------------------------------------------------------------
# Unit 2 (§4.1) — age-derived 4-stage taxonomy.
# ---------------------------------------------------------------------------


def test_stage_band_boundaries() -> None:
  cases = [
    (0, _stage.STARTUP), (11, _stage.STARTUP),
    (12, _stage.EARLY), (35, _stage.EARLY),
    (36, _stage.OPERATIONAL), (83, _stage.OPERATIONAL),
    (84, _stage.MATURE), (240, _stage.MATURE),
  ]
  for months, expected in cases:
    got = _stage.derive_stage(months)
    assert got == expected, f"age {months}mo -> {got}, expected {expected}"


def test_stage_future_dated_start_is_startup() -> None:
  # Negative age (start in the future / pre-revenue) -> startup.
  assert _stage.derive_stage(-3) == _stage.STARTUP


def test_stage_none_age_propagates_none() -> None:
  # No silent default — unknown age returns None for the caller to decide.
  assert _stage.derive_stage(None) is None


def test_business_age_quarters() -> None:
  assert _stage.business_age_quarters(0) == 0
  assert _stage.business_age_quarters(11) == 3
  assert _stage.business_age_quarters(12) == 4
  assert _stage.business_age_quarters(-6) == 0  # future-dated clamps to 0
  assert _stage.business_age_quarters(None) is None


def test_business_age_months_matches_precedent() -> None:
  # Mirrors quarter_grid._whole_months_between arithmetic.
  assert _stage.business_age_months(date(2024, 1, 15), date(2026, 1, 15)) == 24
  assert _stage.business_age_months(date(2024, 1, 20), date(2026, 1, 15)) == 23  # day < start.day
  assert _stage.business_age_months(None, date(2026, 1, 15)) is None


def main() -> int:
  print("running test_fix_1_viability_standard.py")
  print("-" * 70)
  tests = [
    ("u1_revenue_growth_q_known_column", test_revenue_growth_q_in_known_columns),
    ("u1_revenue_growth_metric_key_mapped", test_revenue_growth_metric_key_maps_to_column),
    ("u2_stage_band_boundaries", test_stage_band_boundaries),
    ("u2_stage_future_dated_startup", test_stage_future_dated_start_is_startup),
    ("u2_stage_none_propagates", test_stage_none_age_propagates_none),
    ("u2_business_age_quarters", test_business_age_quarters),
    ("u2_business_age_months_precedent", test_business_age_months_matches_precedent),
  ]
  for name, fn in tests:
    _run(name, fn)
  print("-" * 70)
  passed = sum(1 for _, ok, _ in _RESULTS if ok)
  failed = [(n, why) for n, ok, why in _RESULTS if not ok]
  for name, ok, _ in _RESULTS:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
  print(f"{passed}/{len(_RESULTS)} passed")
  if failed:
    print("FAILURES:")
    for name, why in failed:
      print(f"  {name}: {why}")
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
