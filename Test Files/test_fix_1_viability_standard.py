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
from client_intake_and_finmo.post_intake_viability import constructs as _con  # noqa: E402


def _approx(a, b, tol=1e-6) -> bool:
  return a is not None and b is not None and abs(a - b) <= tol


# A hand-built 3-quarter finmo_json with known values (plus an opening stub
# at quarter_index 0 that must be excluded). Operating-NWC = (AR+inv+prepaid)
# - (AP+deferred); the funding-contaminated totals are deliberately wrong to
# prove they are NOT read.
_FIXTURE = {
  "quarter_rows": [
    {"quarter_index": 0, "revenue": 0, "ebitda": 0},  # stub — must be skipped
    {"quarter_index": 1, "revenue": 100.0, "ebitda": -20.0,
     "changes_in_current_assets": -10.0, "changes_in_current_liabilities": 4.0,
     "accounts_receivable": 30.0, "inventory": 10.0, "prepaid_expenses": 0.0,
     "accounts_payable": 12.0, "deferred_revenue": 0.0,
     "current_assets": 999.0, "current_liabilities": 999.0},  # totals (contaminated) — must be ignored
    {"quarter_index": 2, "revenue": 150.0, "ebitda": 15.0,
     "changes_in_current_assets": -5.0, "changes_in_current_liabilities": 2.0,
     "accounts_receivable": 40.0, "inventory": 12.0, "prepaid_expenses": 0.0,
     "accounts_payable": 15.0, "deferred_revenue": 0.0},
    {"quarter_index": 3, "revenue": 200.0, "ebitda": 40.0,
     "changes_in_current_assets": -6.0, "changes_in_current_liabilities": 3.0,
     "accounts_receivable": 50.0, "inventory": 14.0, "prepaid_expenses": 0.0,
     "accounts_payable": 18.0, "deferred_revenue": 0.0},
  ]
}


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


# ---------------------------------------------------------------------------
# Unit 3 (§2) — the 5 firm-side constructs.
# ---------------------------------------------------------------------------


def test_live_rows_excludes_stub() -> None:
  rows = _con.live_quarter_rows(_FIXTURE)
  assert [r["quarter_index"] for r in rows] == [1, 2, 3], "stub q0 must be excluded, sorted asc"


def test_c1_operating_cash_proxy_signs() -> None:
  # proxy = ebitda + changes_in_current_assets + changes_in_current_liabilities
  s = _con.operating_cash_proxy_series(_con.live_quarter_rows(_FIXTURE))
  by_q = {x["quarter_index"]: x for x in s}
  assert _approx(by_q[1]["value"], -26.0)   # -20 + (-10) + 4
  assert _approx(by_q[1]["margin"], -0.26)  # -26/100
  assert _approx(by_q[2]["value"], 12.0)    # 15 + (-5) + 2
  assert _approx(by_q[3]["value"], 37.0)    # 40 + (-6) + 3


def test_c3_nwc_intensity_uses_operating_subset_not_totals() -> None:
  s = _con.nwc_intensity_series(_con.live_quarter_rows(_FIXTURE))
  by_q = {x["quarter_index"]: x for x in s}
  # q1 operating NWC = (30+10+0) - (12+0) = 28 ; intensity 28/100=0.28
  # (the contaminated 999 totals must NOT appear)
  assert _approx(by_q[1]["nwc"], 28.0)
  assert _approx(by_q[1]["nwc_to_revenue"], 0.28)
  assert _approx(by_q[3]["nwc"], 46.0)  # (50+14)-18


def test_c2_rule_of_40() -> None:
  s = _con.rule_of_40_series(_con.live_quarter_rows(_FIXTURE))
  by_q = {x["quarter_index"]: x for x in s}
  assert by_q[1]["revenue_growth"] is None  # first quarter, no prior
  assert _approx(by_q[2]["revenue_growth"], 0.5)     # (150-100)/100
  assert _approx(by_q[2]["ebitda_margin"], 0.10)     # 15/150
  assert _approx(by_q[2]["rule_of_40"], 0.60)        # 0.5 + 0.10


def test_c4_ebitda_ramp() -> None:
  ramp = _con.ebitda_ramp(_con.live_quarter_rows(_FIXTURE))
  assert ramp["breakeven_quarter"] == 2  # first ebitda >= 0
  # margins [-0.20, 0.10, 0.20] over q [1,2,3] -> OLS slope 0.2
  assert _approx(ramp["margin_slope_per_quarter"], 0.2)
  assert ramp["operating_leverage"] is not None and ramp["operating_leverage"] > 0.0


def test_c5_cumulative_ebitda() -> None:
  res = _con.cumulative_ebitda_series(_con.live_quarter_rows(_FIXTURE))
  by_q = {x["quarter_index"]: x for x in res}
  assert _approx(by_q[1]["cumulative_ebitda"], -20.0)
  assert _approx(by_q[2]["cumulative_ebitda"], -5.0)
  assert _approx(by_q[3]["cumulative_ebitda"], 35.0)


def test_firm_constructs_bundle() -> None:
  b = _con.firm_constructs(_FIXTURE)
  assert b["quarters"] == [1, 2, 3]
  assert _approx(b["cumulative_ebitda"]["final"], 35.0)
  assert b["cumulative_ebitda"]["final_quarter"] == 3
  assert b["ebitda_ramp"]["breakeven_quarter"] == 2


def test_constructs_none_safe_on_empty() -> None:
  # Missing / malformed finmo_json must not crash (no silent degradation
  # to wrong numbers — returns empty / None).
  assert _con.firm_constructs(None)["quarters"] == []
  assert _con.firm_constructs({})["quarters"] == []


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
    ("u3_live_rows_excludes_stub", test_live_rows_excludes_stub),
    ("u3_c1_operating_cash_proxy", test_c1_operating_cash_proxy_signs),
    ("u3_c3_nwc_intensity_operating_subset", test_c3_nwc_intensity_uses_operating_subset_not_totals),
    ("u3_c2_rule_of_40", test_c2_rule_of_40),
    ("u3_c4_ebitda_ramp", test_c4_ebitda_ramp),
    ("u3_c5_cumulative_ebitda", test_c5_cumulative_ebitda),
    ("u3_firm_constructs_bundle", test_firm_constructs_bundle),
    ("u3_constructs_none_safe", test_constructs_none_safe_on_empty),
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
