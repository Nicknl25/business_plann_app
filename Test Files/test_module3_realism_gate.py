"""Module 3 v2 verification — finalize realism gate.

Covers:
  - Lookup table loaded with the v2 default rows (10 metrics).
  - Formula registry has 10 keys, all dispatchable.
  - Validator with synthetic in-band FINMO produces no warnings.
  - Validator with deliberately out-of-band COGS for retail produces a
    `out_of_band_warn` result with full provenance.
  - Validator skips inventory check for software (NAICS 51) per
    applicability rule (legitimate-zero invariant).
  - Validator with `gate_kind = "hard_fail"` raises `RealismBandViolation`.
  - Stub 0 (Q0) is never validated — the formula registry ignores it
    because formulas key on quarter_index >= 1.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_module3_realism_gate.py"`
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

from client_intake_and_finmo.post_intake_realism import (  # noqa: E402
  RealismBandViolation,
  evaluate_realism_formula,
  post_intake_finalize_realism_check_for_metric,
  post_intake_finalize_realism_check_rows,
  registered_realism_formula_keys,
  validate_industry_realism_bands,
)


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
# Synthetic FINMO builders.
# --------------------------------------------------------------------------


def _quarter_row(quarter: int, **fields: Any) -> Dict[str, Any]:
  base = {"quarter_index": quarter}
  base.update(fields)
  return base


def _retail_in_band_finmo(quarters: int = 20) -> Dict[str, Any]:
  # NAICS 455211: cogs ~ 0.82, payroll ~ 0.20, ebitda ~ 5%, net_income ~ 2%.
  # Field names match `FinmoQuarterResult` exactly (cost_of_goods_sold,
  # research_and_development, lease_rent, general_and_administrative).
  rows: List[Dict[str, Any]] = []
  revenue = 1_000_000.0
  for q in range(1, quarters + 1):
    cogs = 0.82 * revenue
    payroll = 0.20 * revenue
    marketing = 0.025 * revenue
    g_and_a = 0.03 * revenue
    lease_rent = 0.0
    r_and_d = 0.0
    ebitda = revenue - cogs - payroll - marketing - g_and_a - lease_rent - r_and_d
    interest = 0.0
    depreciation = 0.0
    pretax = ebitda - interest - depreciation
    taxes = max(0.0, pretax) * 0.18
    net_income = pretax - taxes
    rows.append(_quarter_row(
      q,
      revenue=revenue,
      cost_of_goods_sold=cogs,
      gross_profit=revenue - cogs,
      marketing=marketing,
      research_and_development=r_and_d,
      lease_rent=lease_rent,
      payroll=payroll,
      general_and_administrative=g_and_a,
      ebitda=ebitda,
      interest=interest,
      depreciation=depreciation,
      taxes=taxes,
      net_income=net_income,
      accounts_receivable=revenue * (5.0 / 90.0),
      accounts_payable=(cogs + marketing + g_and_a) * (30.0 / 90.0),
      inventory=cogs * (35.0 / 90.0),
    ))
  return {"quarter_rows": rows}


def _software_in_band_finmo(quarters: int = 20) -> Dict[str, Any]:
  rows: List[Dict[str, Any]] = []
  revenue = 1_000_000.0
  for q in range(1, quarters + 1):
    cogs = 0.30 * revenue
    payroll = 0.45 * revenue
    marketing = 0.10 * revenue
    g_and_a = 0.08 * revenue
    lease_rent = 0.0
    r_and_d = 0.05 * revenue
    ebitda = revenue - cogs - payroll - marketing - g_and_a - lease_rent - r_and_d
    interest = 0.0
    depreciation = 0.0
    pretax = ebitda - interest - depreciation
    taxes = max(0.0, pretax) * 0.21
    net_income = pretax - taxes
    rows.append(_quarter_row(
      q,
      revenue=revenue,
      cost_of_goods_sold=cogs,
      gross_profit=revenue - cogs,
      marketing=marketing,
      research_and_development=r_and_d,
      lease_rent=lease_rent,
      payroll=payroll,
      general_and_administrative=g_and_a,
      ebitda=ebitda,
      interest=interest,
      depreciation=depreciation,
      taxes=taxes,
      net_income=net_income,
      accounts_receivable=revenue * (60.0 / 90.0),
      accounts_payable=(cogs + marketing + g_and_a) * (30.0 / 90.0),
      inventory=0.0,  # software has no inventory
    ))
  return {"quarter_rows": rows}


def _retail_out_of_band_cogs_finmo() -> Dict[str, Any]:
  rows: List[Dict[str, Any]] = []
  revenue = 1_000_000.0
  for q in range(1, 21):
    cogs = 1.30 * revenue
    rows.append(_quarter_row(
      q,
      revenue=revenue,
      cost_of_goods_sold=cogs,
      gross_profit=revenue - cogs,
      payroll=0.20 * revenue,
      marketing=0.025 * revenue,
      research_and_development=0.0,
      lease_rent=0.0,
      general_and_administrative=0.03 * revenue,
      ebitda=-0.555 * revenue,
      interest=0.0,
      depreciation=0.0,
      taxes=0.0,
      net_income=-0.555 * revenue,
      accounts_receivable=revenue * (5.0 / 90.0),
      accounts_payable=(cogs + 0.025 * revenue + 0.03 * revenue) * (30.0 / 90.0),
      inventory=cogs * (35.0 / 90.0),
    ))
  return {"quarter_rows": rows}


# --------------------------------------------------------------------------
# Tests — lookup + formula registry.
# --------------------------------------------------------------------------


def test_lookup_table_has_v3_default_rows() -> None:
  # v3 expanded coverage to ~28 rows and tier-promoted high-confidence
  # metrics from warn -> hard_fail per master-diagnostic Phase 4.
  rows = post_intake_finalize_realism_check_rows()
  assert len(rows) >= 25, f"expected >=25 rows after v3 expansion, got {len(rows)}"
  metric_keys = {row["metric_key"] for row in rows}
  for required in (
    "cogs_percent_of_revenue",
    "gross_margin_percent",
    "marketing_percent_of_revenue",
    "advertising_percent_of_revenue",
    "r_and_d_percent_of_revenue",
    "rent_percent_of_revenue",
    "sga_percent_of_revenue",
    "payroll_percent_of_revenue",
    "depreciation_percent_of_revenue",
    "effective_tax_rate",
    "ebitda_margin",
    "operating_margin_percent",
    "net_income_margin",
    "ar_days_dso",
    "ap_days_dpo",
    "inventory_days",
    "prepaid_expenses_percent_of_revenue",
    "deferred_revenue_percent_of_revenue",
    "ppe_percent_of_revenue",
    "total_assets_to_revenue",
    "owners_capital_percent_of_assets",
    "current_ratio",
    "quick_ratio",
    "debt_to_equity",
    "debt_to_assets",
    "operating_cash_flow_margin",
    "capex_percent_of_revenue",
    "distributions_percent_of_net_income",
  ):
    assert required in metric_keys, f"missing {required} from v3 default rows"
  # v3 promoted these to hard_fail.
  hard_fail_metrics = {row["metric_key"] for row in rows if row.get("gate_kind") == "hard_fail"}
  for required_hf in (
    "cogs_percent_of_revenue",
    "ar_days_dso",
    "ap_days_dpo",
    "ebitda_margin",
    "effective_tax_rate",
  ):
    assert required_hf in hard_fail_metrics, f"v3 expected {required_hf} promoted to hard_fail"
  # v3 universal liquidity ratios stay warn-only.
  warn_metrics = {row["metric_key"] for row in rows if row.get("gate_kind") == "warn"}
  for required_warn in ("current_ratio", "quick_ratio", "payroll_percent_of_revenue"):
    assert required_warn in warn_metrics, f"v3 expected {required_warn} to stay warn-only"


def test_formula_registry_has_full_set() -> None:
  keys = registered_realism_formula_keys()
  # v3 expanded the registry to ~29 formulas covering the line-level metrics
  # in master-diagnostic Part 6.1.
  assert len(keys) >= 25, f"expected >=25 formulas after v3 expansion, got {len(keys)}"
  for required in (
    "cogs_dollars_div_revenue_dollars",
    "gross_margin_div_revenue",
    "marketing_dollars_div_revenue_dollars",
    "payroll_dollars_div_revenue_dollars",
    "ebitda_div_revenue",
    "operating_margin_div_revenue",
    "net_income_div_revenue",
    "ar_days_from_balance_and_revenue",
    "ap_days_from_balance_and_expenses",
    "inventory_days_from_balance_and_cogs",
    "prepaid_expenses_dollars_div_revenue_dollars",
    "deferred_revenue_dollars_div_revenue_dollars",
    "ppe_dollars_div_revenue_dollars",
    "current_ratio",
    "quick_ratio",
    "total_debt_div_total_equity",
    "operating_cash_flow_div_revenue",
    "capex_div_revenue_year_one",
  ):
    assert required in keys, f"missing formula {required}"


def test_formula_evaluates_cogs_correctly() -> None:
  finmo = _retail_in_band_finmo(quarters=4)
  ratio = evaluate_realism_formula(
    "cogs_dollars_div_revenue_dollars",
    model_input_json={},
    finmo_json=finmo,
    quarter_index=1,
  )
  assert ratio is not None
  assert abs(ratio - 0.82) < 1e-6, ratio


def test_formula_returns_none_for_invalid_quarter() -> None:
  finmo = {"quarter_rows": []}
  ratio = evaluate_realism_formula(
    "cogs_dollars_div_revenue_dollars",
    model_input_json={},
    finmo_json=finmo,
    quarter_index=1,
  )
  assert ratio is None


# --------------------------------------------------------------------------
# Tests — validator behavior.
# --------------------------------------------------------------------------


def test_validator_in_band_retail_emits_no_warnings() -> None:
  # Restrict to cogs to keep the test focused. Other metrics may have
  # tolerances that make in-band the synthetic 0.82 number — we only
  # assert COGS specifically.
  rows = [r for r in post_intake_finalize_realism_check_rows() if r["metric_key"] == "cogs_percent_of_revenue"]
  payload = validate_industry_realism_bands(
    model_input_json={},
    finmo_json=_retail_in_band_finmo(),
    business_naics_6="455211",
    ops_json={"business_naics_6": "455211"},
    financials_json={},
    rows_override=rows,
  )
  warnings = payload.get("warnings") or []
  cogs_warnings = [w for w in warnings if w.get("metric_key") == "cogs_percent_of_revenue"]
  assert len(cogs_warnings) == 0, f"unexpected cogs warnings on in-band synthetic: {cogs_warnings[:2]}"


def test_validator_out_of_band_warn_metric_emits_warning_with_provenance() -> None:
  # v3 keeps marketing_percent_of_revenue at warn-mode. Use it for the
  # "warn-mode out-of-band" test so the validator emits a warning rather
  # than raising. (cogs is now hard_fail; the hard_fail behavior is
  # covered by test_validator_hard_fail_raises.)
  rows = [r for r in post_intake_finalize_realism_check_rows() if r["metric_key"] == "marketing_percent_of_revenue"]
  # Build retail FINMO with marketing at 60% of revenue — far above NAICS
  # retail marketing% band (~7-24%) AND outside the low-confidence
  # tolerance envelope (low-confidence tolerance for ratio metrics is
  # 2000 bps = 20pp, so the gate fires when actual is more than 20pp
  # above the band's max).
  finmo = _retail_in_band_finmo()
  for row in finmo["quarter_rows"]:
    row["marketing"] = 0.60 * float(row["revenue"])
  payload = validate_industry_realism_bands(
    model_input_json={},
    finmo_json=finmo,
    business_naics_6="455211",
    ops_json={"business_naics_6": "455211"},
    financials_json={},
    rows_override=rows,
  )
  warnings = [w for w in payload.get("warnings") or [] if w.get("metric_key") == "marketing_percent_of_revenue"]
  assert len(warnings) > 0, f"expected at least one out-of-band warning for marketing at 60%"
  w = warnings[0]
  assert w.get("status") == "out_of_band_warn", w
  assert w.get("actual_value") is not None and abs(float(w["actual_value"]) - 0.60) < 1e-6, w
  for key in (
    "band_min", "band_max", "band_target", "band_naics_code",
    "band_naics_level", "band_confidence_tier", "band_data_source",
    "band_trust_flag", "tolerance_applied_bps", "effective_min", "effective_max",
    "governs_lever_id",
  ):
    assert key in w, f"warning missing provenance key {key}: {w}"
  assert w.get("governs_lever_id") == "expenses::Marketing", w


def test_validator_v3_promoted_cogs_to_hard_fail_raises() -> None:
  # v3 promoted cogs_percent_of_revenue to hard_fail. Out-of-band COGS now
  # raises directly without test-time monkey-patching.
  rows = [r for r in post_intake_finalize_realism_check_rows() if r["metric_key"] == "cogs_percent_of_revenue"]
  assert rows and rows[0].get("gate_kind") == "hard_fail", rows
  raised = False
  try:
    validate_industry_realism_bands(
      model_input_json={},
      finmo_json=_retail_out_of_band_cogs_finmo(),
      business_naics_6="455211",
      ops_json={"business_naics_6": "455211"},
      financials_json={},
      rows_override=rows,
    )
  except RealismBandViolation as exc:
    raised = True
    msg = str(exc)
    assert "cogs_percent_of_revenue" in msg, msg
    assert "actual=1.30" in msg, msg
    assert hasattr(exc, "results"), "violation must carry results"
  assert raised, "expected RealismBandViolation on hard_fail cogs"


def test_validator_skips_inventory_for_software_naics() -> None:
  rows = [r for r in post_intake_finalize_realism_check_rows() if r["metric_key"] == "inventory_days"]
  payload = validate_industry_realism_bands(
    model_input_json={},
    finmo_json=_software_in_band_finmo(),
    business_naics_6="511210",
    ops_json={"business_naics_6": "511210"},
    financials_json={},
    rows_override=rows,
  )
  results = payload.get("results") or []
  inventory_results = [r for r in results if r.get("metric_key") == "inventory_days"]
  assert len(inventory_results) >= 1
  for r in inventory_results:
    assert r.get("status") == "skipped", f"software inventory should skip: {r}"
    assert r.get("reason", "").startswith("skip_inventory_not_applicable_naics2_"), r
  warnings = [w for w in payload.get("warnings") or [] if w.get("metric_key") == "inventory_days"]
  assert len(warnings) == 0, f"software inventory must not emit warnings: {warnings}"


def test_validator_synthetic_warn_to_hard_fail_promotion_works() -> None:
  # Belt-and-suspenders test: synthetically promote a warn-mode metric to
  # hard_fail at runtime and confirm the validator honors it. Confirms the
  # gate_kind is the only switch between warn and raise behavior.
  rows = [
    {**r, "gate_kind": "hard_fail"}
    for r in post_intake_finalize_realism_check_rows()
    if r["metric_key"] == "marketing_percent_of_revenue"
  ]
  finmo = _retail_in_band_finmo()
  for row in finmo["quarter_rows"]:
    row["marketing"] = 0.60 * float(row["revenue"])
  raised = False
  try:
    validate_industry_realism_bands(
      model_input_json={},
      finmo_json=finmo,
      business_naics_6="455211",
      ops_json={"business_naics_6": "455211"},
      financials_json={},
      rows_override=rows,
    )
  except RealismBandViolation:
    raised = True
  assert raised, "synthetic hard_fail promotion should raise"


def test_validator_excludes_stub_zero_q0() -> None:
  # The formulas key on quarter_index >= 1 (per FINMO's quarter_rows shape).
  # If a synthetic finmo had a Q0 row, the validator's _finmo_quarter_rows
  # filter drops it. We simulate by adding a Q0 row with garbage data and
  # confirming no result references quarter_index = 0.
  finmo = _retail_in_band_finmo()
  finmo["quarter_rows"].insert(0, {
    "quarter_index": 0,
    "revenue": 1.0,
    "cogs": 999.0,  # would be 99900% if validated — must not be
    "payroll": 0.0,
  })
  rows = [r for r in post_intake_finalize_realism_check_rows() if r["metric_key"] == "cogs_percent_of_revenue"]
  payload = validate_industry_realism_bands(
    model_input_json={},
    finmo_json=finmo,
    business_naics_6="455211",
    ops_json={"business_naics_6": "455211"},
    financials_json={},
    rows_override=rows,
  )
  for result in payload.get("results") or []:
    qi = result.get("quarter_index")
    assert qi is None or int(qi) >= 1, f"validator must skip Q0 (intake fact): {result}"
  # Specifically: no out-of-band warning for cogs even though we planted
  # cogs=999 at Q0. The quarter_rows[1..20] are all in-band, and Q0 was
  # not validated.
  cogs_warnings = [w for w in payload.get("warnings") or [] if w.get("metric_key") == "cogs_percent_of_revenue"]
  assert len(cogs_warnings) == 0, f"Q0 leakage detected: {cogs_warnings}"


def test_validator_no_business_naics_returns_no_warnings() -> None:
  # When NAICS is missing, the resolver returns no_coverage; rows with
  # gate_kind = "warn" silently no-op (cannot validate without a band).
  rows = [r for r in post_intake_finalize_realism_check_rows() if r["metric_key"] == "cogs_percent_of_revenue"]
  payload = validate_industry_realism_bands(
    model_input_json={},
    finmo_json=_retail_out_of_band_cogs_finmo(),
    business_naics_6=None,
    ops_json={},
    financials_json={},
    rows_override=rows,
  )
  warnings = payload.get("warnings") or []
  assert len(warnings) == 0, warnings


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_module3_realism_gate.py")
  print("-" * 70)
  tests = [
    ("lookup_has_v3_default_rows", test_lookup_table_has_v3_default_rows),
    ("formula_registry_has_full_set", test_formula_registry_has_full_set),
    ("formula_evaluates_cogs_correctly", test_formula_evaluates_cogs_correctly),
    ("formula_returns_none_for_invalid_quarter", test_formula_returns_none_for_invalid_quarter),
    ("validator_in_band_retail_no_warnings", test_validator_in_band_retail_emits_no_warnings),
    ("validator_out_of_band_warn_metric_warns", test_validator_out_of_band_warn_metric_emits_warning_with_provenance),
    ("validator_v3_promoted_cogs_hard_fail_raises", test_validator_v3_promoted_cogs_to_hard_fail_raises),
    ("validator_skips_inventory_for_software", test_validator_skips_inventory_for_software_naics),
    ("validator_synthetic_promotion_works", test_validator_synthetic_warn_to_hard_fail_promotion_works),
    ("validator_excludes_stub_zero_q0", test_validator_excludes_stub_zero_q0),
    ("validator_no_naics_no_warnings", test_validator_no_business_naics_returns_no_warnings),
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
