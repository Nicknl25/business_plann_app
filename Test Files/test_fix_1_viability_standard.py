"""Fix #1 — Viability Standard tests.

Built incrementally per the build order in
docs/architecture/fix_1_viability_standard_spec.md (@ 7e747a8).

Unit 1 (§5.1) — revenue_growth_q registered in the cohort resolver maps.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_fix_1_viability_standard.py"`
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Callable, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_solver import cohort_band_resolver as _cbr  # noqa: E402


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


def main() -> int:
  print("running test_fix_1_viability_standard.py")
  print("-" * 70)
  tests = [
    ("u1_revenue_growth_q_known_column", test_revenue_growth_q_in_known_columns),
    ("u1_revenue_growth_metric_key_mapped", test_revenue_growth_metric_key_maps_to_column),
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
