"""Module 3 v3 — schedule sanity cross-check tests (Task 3.8).

Wage realism, productivity realism, debt rate realism, capex/PPE chain.
Confirms each check produces meaningful in-band/out-of-band results
with full provenance, and that None inputs (missing schedule) skip
gracefully.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module3_schedule_sanity.py"`
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

from client_intake_and_finmo.post_intake_realism import validate_schedule_sanity  # noqa: E402


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
# Synthetic builders.
# --------------------------------------------------------------------------


def _payroll_for_naics(*, naics: str) -> Dict[str, Any]:
  # 5 supporting-staff FTEs at NAICS-typical wages. 455211 (retail
  # superstore) NAICS-3 wage is ~$39K; we set $40K to be inside band.
  rows = []
  for q in range(1, 21):
    rows.append({
      "quarter_index": q,
      "staffing_class": "supporting_staff",
      "starting_fte": 5.0,
      "ending_fte": 5.0,
      "annual_wage": 40_000.0,
    })
  return {"payroll_headcount_grid": rows}


def _payroll_with_implausible_wages() -> Dict[str, Any]:
  rows = []
  for q in range(1, 21):
    rows.append({
      "quarter_index": q,
      "staffing_class": "supporting_staff",
      "starting_fte": 5.0,
      "ending_fte": 5.0,
      "annual_wage": 250_000.0,  # 6x NAICS-typical retail wage
    })
  return {"payroll_headcount_grid": rows}


def _finmo_with_revenue_per_fte(*, revenue_per_quarter: float = 250_000.0) -> Dict[str, Any]:
  rows = []
  for q in range(1, 21):
    rows.append({
      "quarter_index": q,
      "revenue": revenue_per_quarter,
    })
  return {"quarter_rows": rows}


def _finmo_with_debt_rate(*, debt_open: float = 1_000_000.0, annual_rate: float = 0.085) -> Dict[str, Any]:
  rows = []
  quarterly_rate = annual_rate / 4.0
  debt_close = debt_open * 0.99  # tiny paydown
  rows.append({
    "quarter_index": 1,
    "debt_opening_balance": debt_open,
    "debt_closing_balance": debt_close,
    "debt_interest_rate": quarterly_rate,
    "debt_interest_expense": ((debt_open + debt_close) / 2.0) * quarterly_rate,
  })
  for q in range(2, 21):
    rows.append({
      "quarter_index": q,
      "debt_opening_balance": debt_close,
      "debt_closing_balance": debt_close,
      "debt_interest_rate": quarterly_rate,
      "debt_interest_expense": debt_close * quarterly_rate,
    })
  return {"quarter_rows": rows}


def _finmo_with_capex_ppe_chain(
  *,
  ppe_q1: float = 100_000.0,
  capex_per_quarter: float = 10_000.0,
  depreciation_per_quarter: float = 5_000.0,
) -> Dict[str, Any]:
  rows = []
  ppe = ppe_q1
  for q in range(1, 21):
    rows.append({
      "quarter_index": q,
      "ppe": ppe,
      "capital_expenditures": capex_per_quarter,
      "depreciation": depreciation_per_quarter,
    })
    ppe += (capex_per_quarter - depreciation_per_quarter)
  return {"quarter_rows": rows}


# --------------------------------------------------------------------------
# Tests.
# --------------------------------------------------------------------------


def test_returns_payload_shape_when_no_schedules() -> None:
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json={"quarter_rows": []},
    business_naics_6="455211",
    payroll_headcount=None,
    financials_json=None,
  )
  for k in ("results", "warnings", "warning_count", "checked_metric_count", "result_count"):
    assert k in payload, f"missing payload key {k}: {payload}"
  assert payload.get("result_count", 0) >= 0


def test_wage_realism_in_band_emits_no_warning() -> None:
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json={"quarter_rows": []},
    business_naics_6="455211",
    payroll_headcount=_payroll_for_naics(naics="455211"),
    financials_json={},
  )
  wage_results = [r for r in payload["results"] if r.get("metric_key") == "avg_wage_per_fte"]
  assert wage_results, "expected at least one avg_wage_per_fte result"
  for r in wage_results:
    if r.get("status") == "skipped":
      continue
    assert r["status"] == "in_band", f"$40K wage should be near retail NAICS band: {r}"


def test_wage_realism_out_of_band_emits_warning() -> None:
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json={"quarter_rows": []},
    business_naics_6="455211",
    payroll_headcount=_payroll_with_implausible_wages(),
    financials_json={},
  )
  wage_warnings = [w for w in payload["warnings"] if w.get("metric_key") == "avg_wage_per_fte"]
  assert len(wage_warnings) > 0, f"expected wage realism warning at $250K wage: {payload}"
  w = wage_warnings[0]
  assert "wage_positioning_tier_implausible" in (w.get("reason") or ""), w
  assert w.get("governs_lever_id") == "payroll_headcount_schedule.wage_positioning_tier", w


def test_productivity_realism_emits_a_result() -> None:
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json=_finmo_with_revenue_per_fte(revenue_per_quarter=250_000.0),
    business_naics_6="455211",
    payroll_headcount=_payroll_for_naics(naics="455211"),
    financials_json={},
  )
  prod_results = [r for r in payload["results"] if r.get("metric_key") == "revenue_per_fte"]
  assert prod_results, f"expected productivity result: {payload}"


def test_debt_rate_realism_no_debt_returns_no_result() -> None:
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json={"quarter_rows": [{"quarter_index": 1, "debt_opening_balance": 0.0}]},
    business_naics_6="455211",
    payroll_headcount={},
    financials_json={},
  )
  debt_results = [r for r in payload["results"] if r.get("metric_key") == "sba_initial_interest_rate"]
  assert debt_results == [], f"no debt should produce no debt-rate result: {debt_results}"


def test_debt_rate_realism_with_reasonable_rate() -> None:
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json=_finmo_with_debt_rate(annual_rate=0.085),
    business_naics_6="455211",
    payroll_headcount={},
    financials_json={
      "annual_interest_payment": 85_000.0,
      "total_debt_outstanding": 1_000_000.0,
    },
  )
  debt_results = [r for r in payload["results"] if r.get("metric_key") == "sba_initial_interest_rate"]
  assert debt_results, f"expected debt-rate result: {payload}"


def test_capex_ppe_chain_consistent() -> None:
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json=_finmo_with_capex_ppe_chain(),
    business_naics_6="455211",
    payroll_headcount={},
    financials_json={},
  )
  chain_results = [r for r in payload["results"] if r.get("metric_key") == "capex_ppe_depreciation_chain"]
  assert chain_results, "expected capex_ppe_depreciation_chain result"
  for r in chain_results:
    assert r["status"] == "in_band", f"clean capex/PPE/depreciation chain should be in_band: {r}"


def test_capex_ppe_chain_inconsistent_warns() -> None:
  # Build a finmo where ppe_q4 - ppe_q1 != capex - depreciation. That's a
  # statement-vs-schedule mismatch the gate must surface.
  rows = []
  for q in range(1, 21):
    rows.append({
      "quarter_index": q,
      "ppe": 100_000.0,  # constant — but capex injects PPE while depreciation removes
      "capital_expenditures": 50_000.0,
      "depreciation": 5_000.0,
    })
  finmo = {"quarter_rows": rows}
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json=finmo,
    business_naics_6="455211",
    payroll_headcount={},
    financials_json={},
  )
  warnings = [w for w in payload["warnings"] if w.get("metric_key") == "capex_ppe_depreciation_chain"]
  assert warnings, f"expected chain warning when PPE doesn't track capex - depreciation: {payload}"
  w = warnings[0]
  assert "capex_ppe_depreciation_chain_inconsistent" in (w.get("reason") or ""), w


def test_validate_schedule_sanity_handles_invalid_naics_gracefully() -> None:
  # No NAICS = resolver can't return bands; checks should skip cleanly.
  payload = validate_schedule_sanity(
    model_input_json={},
    finmo_json=_finmo_with_revenue_per_fte(),
    business_naics_6=None,
    payroll_headcount=_payroll_for_naics(naics=""),
    financials_json={},
  )
  for r in payload["results"]:
    if r.get("metric_key") in ("avg_wage_per_fte", "revenue_per_fte"):
      assert r["status"] in ("skipped",), f"naics-less band lookup should skip: {r}"


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_module3_schedule_sanity.py")
  print("-" * 70)
  tests = [
    ("payload_shape_when_no_schedules", test_returns_payload_shape_when_no_schedules),
    ("wage_realism_in_band_no_warning", test_wage_realism_in_band_emits_no_warning),
    ("wage_realism_out_of_band_warns", test_wage_realism_out_of_band_emits_warning),
    ("productivity_realism_emits_result", test_productivity_realism_emits_a_result),
    ("debt_rate_no_debt_no_result", test_debt_rate_realism_no_debt_returns_no_result),
    ("debt_rate_reasonable_emits_result", test_debt_rate_realism_with_reasonable_rate),
    ("capex_ppe_chain_consistent_in_band", test_capex_ppe_chain_consistent),
    ("capex_ppe_chain_inconsistent_warns", test_capex_ppe_chain_inconsistent_warns),
    ("schedule_sanity_invalid_naics_graceful", test_validate_schedule_sanity_handles_invalid_naics_gracefully),
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
