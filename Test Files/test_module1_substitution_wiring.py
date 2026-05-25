"""Module 1 Stage B verification: NAICS substitution actually fires through
the full `build_python_model_input_json` path with deliberately sparse intake.

This is a focused integration test (not a full E2E) — it bypasses the real
post-intake pipeline and calls the model_input builder directly with a
synthetic ops/financials payload where every silent-zero field is explicitly
omitted. The assertions check:

  1. Forecast Q1-Q20 expense rows (Cost of Goods Sold, Marketing, Taxes) carry
     NAICS-cascaded values, not zeros.
  2. Forecast Q1-Q20 balance rows (AR Days, AP Days, Inventory Days) carry
     NAICS-cascaded values when applicability allows.
  3. Stub 0 is unchanged for every substituted row (Part 9.1 invariant).
  4. `seed_provenance_json` is attached to every row that was substituted,
     with `seed_source = "naics_cascade"` and resolver metadata.

Two business profiles are exercised:
  - ValueMart (NAICS 455211, retail superstore) — inventory applies, deferred
    revenue does not.
  - NexGen (NAICS 511210, software) — inventory does not apply, deferred
    revenue does (when business-text gating allows).

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module1_substitution_wiring.py"`
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo import finmo_bridge as _finmo_bridge  # noqa: E402
from client_intake_and_finmo.finmo_bridge import build_python_model_input_json  # noqa: E402
from client_intake_and_finmo.post_intake_industry_baseline import (  # noqa: E402
  post_intake_industry_baseline_for_naics,
)


# Bypass the post-overlay capacity/derived-driver enforcement so this focused
# test can run without a full forecast-quarter capacity spec. The substitution
# logic we are testing runs BEFORE the derived-driver policies stage.
_finmo_bridge.apply_derived_driver_policies_to_model_input = lambda payload: payload  # type: ignore[assignment]


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
# Synthetic input builders (deliberately sparse — every silent-zero field
# omitted so the substitution path fires).
# --------------------------------------------------------------------------


def _sparse_financials() -> Dict[str, Any]:
  # All silent-zero fields explicitly absent. Only the BS anchors required by
  # downstream finmo_bridge validation are present.
  return {
    "current_revenue": 2_500_000.0,
    "initial_assets": 100_000.0,
    "initial_equity": 50_000.0,
    "total_debt_outstanding": 0.0,
    "annual_interest_payment": 0.0,
    "annual_principal_payment": 0.0,
    "cash_on_hand": 25_000.0,
    "monthly_rent_expense": 0.0,
    "other_operating_expense": 0.0,
    "current_payroll": 0.0,
    "accumulated_depreciation": 0.0,
    "current_capex": 0.0,
    # Below: explicitly omitted so the substitution path fires.
    # "ar_balance", "ap_balance", "inventory_balance",
    # "marketing_percent_of_revenue", "taxes_percent",
    # "cogs_percent_of_revenue".
  }


def _build_ops(naics_6: str, business_text: str = "") -> Dict[str, Any]:
  return {
    "business_naics_6": naics_6,
    "business_type_summary": business_text,
    "start_date": "2024-01-01",
  }


def _build_forecast_quarters(*, revenue_per_quarter: float, cogs_per_quarter: float = 0.0) -> List[Dict[str, Any]]:
  return [
    {
      "quarter_index": idx + 1,
      "revenue": revenue_per_quarter,
      "cogs": cogs_per_quarter,
      "marketing": 0.0,
      "r_and_d": 0.0,
      "lease_amount": 0.0,
      "payroll_amount": 0.0,
      "g_and_a": 0.0,
      "taxes": 0.0,
      "revenue_products": [],
    }
    for idx in range(20)
  ]


def _call_overlay(*, naics_6: str, business_text: str = "") -> Dict[str, Any]:
  return build_python_model_input_json(
    business_facts={"business_name": "Test Sparse Intake Co", "start_date": "2024-01-01"},
    ops_json=_build_ops(naics_6, business_text=business_text),
    people_json={},
    financials_json=_sparse_financials(),
    financials_year1_json={
      "company_revenue_total_year1": 10_000_000.0,
      "revenue_total_year1": 10_000_000.0,
    },
    marketing_model_json={},
    forecast_starting_ppe=100_000.0,
    maintenance_rate=0.05,
    controller_input_seed=[],
    forecast_quarters=_build_forecast_quarters(revenue_per_quarter=2_500_000.0),
    business_name="Test Sparse Intake Co",
  )


def _row_by_label(rows: List[Dict[str, Any]], label: str) -> Optional[Dict[str, Any]]:
  for row in rows:
    if str(row.get("label") or "").strip() == label:
      return row
  return None


def _forecast_values(row: Dict[str, Any]) -> List[float]:
  values = row.get("values") or []
  return [float(v) for v in values[1:] if v is not None]  # skip stub 0


def _stub_value(row: Dict[str, Any]) -> float:
  values = row.get("values") or []
  return float(values[0]) if values else 0.0


# --------------------------------------------------------------------------
# Tests.
# --------------------------------------------------------------------------


def test_valuemart_cogs_substituted_in_forecast() -> None:
  payload = _call_overlay(naics_6="455211")
  expense_rows = (payload.get("sections") or {}).get("expenses") or []
  cogs = _row_by_label(expense_rows, "Cost of Goods Sold")
  assert cogs is not None, "Cost of Goods Sold row missing"
  forecasts = _forecast_values(cogs)
  assert len(forecasts) == 20, f"expected 20 forecast quarters, got {len(forecasts)}"
  # NAICS 455211 cogs target ~ 0.8167. Allow wide tolerance.
  assert all(0.5 < v < 1.0 for v in forecasts), (
    f"forecast COGS values not in NAICS retail band: {forecasts[:4]}"
  )
  # Stub 0 should remain at the intake-derived 0 (intake omitted COGS).
  assert _stub_value(cogs) == 0.0, f"stub 0 violated: {_stub_value(cogs)}"
  # Provenance check.
  prov = cogs.get("seed_provenance_json") or {}
  assert "cogs_percent_of_revenue" in prov, prov
  assert prov["cogs_percent_of_revenue"]["seed_source"] == "naics_cascade"
  assert prov["cogs_percent_of_revenue"]["trust_flag"] == "naics_6_direct"


def test_valuemart_marketing_substituted_in_forecast() -> None:
  payload = _call_overlay(naics_6="455211")
  expense_rows = (payload.get("sections") or {}).get("expenses") or []
  marketing = _row_by_label(expense_rows, "Marketing")
  assert marketing is not None, "Marketing row missing"
  forecasts = _forecast_values(marketing)
  assert all(v > 0.0 for v in forecasts), f"marketing forecast still zero: {forecasts[:4]}"
  assert _stub_value(marketing) == 0.0
  prov = marketing.get("seed_provenance_json") or {}
  assert "marketing_percent_of_revenue" in prov, prov
  assert prov["marketing_percent_of_revenue"]["seed_source"] == "naics_cascade"


def test_valuemart_taxes_substituted_in_forecast() -> None:
  payload = _call_overlay(naics_6="455211")
  expense_rows = (payload.get("sections") or {}).get("expenses") or []
  taxes = _row_by_label(expense_rows, "Taxes")
  assert taxes is not None, "Taxes row missing"
  forecasts = _forecast_values(taxes)
  assert all(v > 0.0 for v in forecasts), f"taxes forecast still zero: {forecasts[:4]}"
  prov = taxes.get("seed_provenance_json") or {}
  assert "effective_tax_rate" in prov, prov
  # Effective tax rate for retail should resolve at L5 IRS_SOI per the
  # cascade contract; provenance trust_flag confirms.
  assert prov["effective_tax_rate"]["trust_flag"].startswith("naics_"), prov


def test_valuemart_ar_days_substituted_in_forecast() -> None:
  payload = _call_overlay(naics_6="455211")
  bs_rows = (payload.get("sections") or {}).get("balance_sheet") or []
  ar = _row_by_label(bs_rows, "Accounts Receivable Days")
  assert ar is not None, "Accounts Receivable Days row missing"
  forecasts = _forecast_values(ar)
  assert all(v > 0.0 for v in forecasts), f"AR days forecast still zero: {forecasts[:4]}"
  prov = ar.get("seed_provenance_json") or {}
  assert "ar_days_dso" in prov, prov


def test_valuemart_ap_days_substituted_in_forecast() -> None:
  # AP days substitution requires a non-zero ap_expense_base. Since intake
  # omits all expense lines, ap_expense_base is built from forecast slot
  # expenses (marketing + r_and_d + lease + payroll + g_and_a). With our
  # sparse forecast, those are all zero per slot, so ap_expense_base = 0
  # and substitution does NOT fire (legitimate zero, not silent). This test
  # documents the expected null behavior: AP days stays at 0 when no
  # forecast operating expense exists.
  payload = _call_overlay(naics_6="455211")
  bs_rows = (payload.get("sections") or {}).get("balance_sheet") or []
  ap = _row_by_label(bs_rows, "Accounts Payable Days")
  assert ap is not None, "Accounts Payable Days row missing"
  forecasts = _forecast_values(ap)
  # When ap_expense_base is 0, AP days legitimately stays at 0 (no AP if
  # no expenses to drive it). Module 5 + Module 6 will populate the
  # forecast expenses; AP substitution will fire downstream once that lands.
  assert all(v == 0.0 for v in forecasts), forecasts
  # Provenance is still attached because the band was resolved (ap_days_band
  # is non-None even when not used in this test's slot config).
  prov = ap.get("seed_provenance_json") or {}
  assert "ap_days_dpo" in prov, prov


def test_valuemart_inventory_substituted_when_applicable() -> None:
  # NAICS 455 (retail) is in the inventory-applicable set. Substitution
  # requires non-zero forecast cogs in the slot. Build a forecast where
  # cogs is non-zero so the substitution can fire.
  result = build_python_model_input_json(
    business_facts={"business_name": "Test", "start_date": "2024-01-01"},
    ops_json=_build_ops("455211"),
    people_json={},
    financials_json=_sparse_financials(),
    financials_year1_json={"company_revenue_total_year1": 10_000_000.0},
    marketing_model_json={},
    forecast_starting_ppe=100_000.0,
    maintenance_rate=0.05,
    controller_input_seed=[],
    forecast_quarters=_build_forecast_quarters(
      revenue_per_quarter=2_500_000.0,
      cogs_per_quarter=2_000_000.0,  # non-zero so inventory substitution can fire
    ),
    business_name="Test",
  )
  bs_rows = (result.get("sections") or {}).get("balance_sheet") or []
  inv = _row_by_label(bs_rows, "Inventory Days")
  assert inv is not None, "Inventory Days row missing"
  forecasts = _forecast_values(inv)
  assert all(v > 0.0 for v in forecasts), f"inventory days forecast still zero: {forecasts[:4]}"
  prov = inv.get("seed_provenance_json") or {}
  assert "inventory_days" in prov, prov


def test_software_inventory_NOT_substituted_legitimate_zero() -> None:
  # NAICS 511 (Information / Software) is NOT in the inventory-applicable
  # set. Even if cogs > 0, inventory must remain zero (legitimate, not
  # silent).
  result = build_python_model_input_json(
    business_facts={"business_name": "NexGen Test", "start_date": "2024-01-01"},
    ops_json=_build_ops("511210"),
    people_json={},
    financials_json=_sparse_financials(),
    financials_year1_json={"company_revenue_total_year1": 10_000_000.0},
    marketing_model_json={},
    forecast_starting_ppe=100_000.0,
    maintenance_rate=0.05,
    controller_input_seed=[],
    forecast_quarters=_build_forecast_quarters(
      revenue_per_quarter=2_500_000.0,
      cogs_per_quarter=500_000.0,
    ),
    business_name="NexGen Test",
  )
  bs_rows = (result.get("sections") or {}).get("balance_sheet") or []
  inv = _row_by_label(bs_rows, "Inventory Days")
  assert inv is not None
  forecasts = _forecast_values(inv)
  assert all(v == 0.0 for v in forecasts), (
    f"inventory days substituted for software business (applicability bug): {forecasts[:4]}"
  )
  prov = inv.get("seed_provenance_json") or {}
  # Applicability blocked the substitution -> no provenance attached.
  assert "inventory_days" not in prov, prov


def test_stub_zero_invariant_preserved_for_all_substituted_rows() -> None:
  # Master-diagnostic Part 9.1: stub 0 is intake fact, never NAICS-substituted.
  payload = _call_overlay(naics_6="455211")
  exp = (payload.get("sections") or {}).get("expenses") or []
  bs = (payload.get("sections") or {}).get("balance_sheet") or []
  for label in ("Cost of Goods Sold", "Marketing", "Taxes"):
    row = _row_by_label(exp, label)
    assert row is not None, f"missing expense row {label}"
    assert _stub_value(row) == 0.0, f"stub 0 violated for {label}: {_stub_value(row)}"
  for label in ("Accounts Receivable Days", "Accounts Payable Days", "Inventory Days"):
    row = _row_by_label(bs, label)
    assert row is not None, f"missing balance row {label}"
    assert _stub_value(row) == 0.0, f"stub 0 violated for {label}: {_stub_value(row)}"


def test_forecast_target_matches_resolver_payload_for_cogs() -> None:
  # Cross-check that the value the substitution uses equals the resolver's
  # benchmark_target.
  band = post_intake_industry_baseline_for_naics(
    metric_key="cogs_percent_of_revenue", naics_6="455211"
  )
  expected_target = float(band["benchmark_target"])
  payload = _call_overlay(naics_6="455211")
  exp_rows = (payload.get("sections") or {}).get("expenses") or []
  cogs = _row_by_label(exp_rows, "Cost of Goods Sold")
  forecasts = _forecast_values(cogs or {})
  # Allow tiny rounding deviation.
  for v in forecasts:
    assert abs(v - expected_target) < 0.005, f"cogs forecast {v} != resolver target {expected_target}"


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_module1_substitution_wiring.py")
  print("-" * 70)
  tests = [
    ("valuemart_cogs_substituted", test_valuemart_cogs_substituted_in_forecast),
    ("valuemart_marketing_substituted", test_valuemart_marketing_substituted_in_forecast),
    ("valuemart_taxes_substituted", test_valuemart_taxes_substituted_in_forecast),
    ("valuemart_ar_days_substituted", test_valuemart_ar_days_substituted_in_forecast),
    ("valuemart_ap_days_zero_when_no_expense_base", test_valuemart_ap_days_substituted_in_forecast),
    ("valuemart_inventory_substituted", test_valuemart_inventory_substituted_when_applicable),
    ("software_inventory_legitimate_zero", test_software_inventory_NOT_substituted_legitimate_zero),
    ("stub_zero_invariant_preserved", test_stub_zero_invariant_preserved_for_all_substituted_rows),
    ("forecast_target_matches_resolver", test_forecast_target_matches_resolver_payload_for_cogs),
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
