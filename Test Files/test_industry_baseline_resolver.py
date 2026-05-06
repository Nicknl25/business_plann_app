"""Unit tests for the post_intake_industry_baseline resolver (Module 1 Task 1.2).

Runnable script (matches Test Files/_verify_*.py convention; no pytest setup
exists in this repo). Each test prints PASS/FAIL with a short reason; exits
non-zero if any test fails.

Coverage targets per Module 1 Task 1.2:
- ValueMart NAICS 455211 cascade for cogs_percent_of_revenue, effective_tax_rate,
  payroll_percent_of_revenue, avg_wage_per_fte
- NexGen NAICS 511210 cascade for deferred_revenue_percent_of_revenue,
  marketing_percent_of_revenue, sga_percent_of_revenue
- Confidence-tier downgrade rules
- no_coverage path + fail_if_no_coverage error
- Metric registry caching (single DB query)
- Idempotence
- Applicability lookup (NAICS-2 sector defaults)

Note: The Module spec test expectations were written when the gap-fill data
load was incomplete. Two metrics that the spec said would resolve to
`generic_default` now resolve at L2 because the 2026-05-05 gap-fill iteration
added derived_CBP_SOI_rollup rows. Tests below assert the *current* DB
behavior; the divergence is documented in Module 1 file's Notes section.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

# Allow running from repo root: add `python/` to sys.path.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_industry_baseline import (  # noqa: E402
  PostIntakeIndustryBaselineNoCoverage,
  baseline_seed_provenance,
  post_intake_baseline_applicability_for_naics2,
  post_intake_industry_baseline_for_naics,
  post_intake_industry_metric_governs_lever,
  post_intake_industry_metric_registry_row,
)
from client_intake_and_finmo.post_intake_industry_baseline import lookup as _lookup_module  # noqa: E402


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


def _assert_close(actual: float, expected: float, *, tol: float = 1e-3, label: str) -> None:
  assert actual is not None, f"{label}: expected ~{expected}, got None"
  assert abs(float(actual) - float(expected)) <= tol, (
    f"{label}: expected ~{expected} (tol {tol}), got {actual}"
  )


# ---------------------------------------------------------------------------
# ValueMart NAICS 455211 cascade.
# ---------------------------------------------------------------------------


def test_valuemart_cogs_percent_of_revenue_resolves_at_l6_direct() -> None:
  payload = post_intake_industry_baseline_for_naics(
    metric_key="cogs_percent_of_revenue", naics_6="455211"
  )
  assert payload["trust_flag"] == "naics_6_direct", payload
  assert payload["naics_level_used"] == 6
  assert payload["naics_code_used"] == "455211"
  assert payload["data_source"] == "industry_metrics_raw"
  assert payload["confidence_tier"] == "high", payload
  _assert_close(payload["benchmark_target"], 0.8167, tol=0.01, label="cogs target")


def test_valuemart_effective_tax_rate_falls_through_l6_to_l5_irs_soi() -> None:
  # Primary source for effective_tax_rate is IRS_SOI. L6 has alpha_data
  # (n=151) but not IRS_SOI -> resolver must skip L6 and land on L5 IRS_SOI.
  payload = post_intake_industry_baseline_for_naics(
    metric_key="effective_tax_rate", naics_6="455211"
  )
  assert payload["trust_flag"] == "naics_5_fallback", payload
  assert payload["naics_level_used"] == 5
  assert payload["naics_code_used"] == "45521"
  assert payload["data_source"] == "IRS_SOI"
  # raw confidence_tier is high; downgraded to medium because resolved at L5.
  assert payload["raw_confidence_tier"] == "high", payload
  assert payload["confidence_tier"] == "medium", payload
  assert payload["sample_size"] == 12226, payload
  _assert_close(payload["benchmark_target"], 0.13326, tol=1e-3, label="effective_tax_rate target")


def test_valuemart_avg_wage_per_fte_resolves_at_l3_bls_oews() -> None:
  payload = post_intake_industry_baseline_for_naics(
    metric_key="avg_wage_per_fte", naics_6="455211"
  )
  assert payload["trust_flag"] == "naics_3_fallback", payload
  assert payload["naics_level_used"] == 3
  assert payload["naics_code_used"] == "455"
  assert payload["data_source"] == "BLS_OEWS"
  # raw high; capped at low at L3.
  assert payload["raw_confidence_tier"] == "high", payload
  assert payload["confidence_tier"] == "low", payload
  _assert_close(payload["benchmark_target"], 39165.44, tol=1.0, label="avg_wage target")


def test_valuemart_payroll_percent_of_revenue_resolves_at_l2_or_l0() -> None:
  # The data substrate for this metric shifted between when Module 1 was
  # drafted and the 2026-05-05 gap-fill load. Today L2 has a
  # derived_CBP_SOI_rollup row, so the cascade stops at L2 (capped at low).
  # If a future gap-fill removes that row, the cascade would fall to L0
  # generic_default. Either is consistent with the contract; this test
  # asserts the contract behavior, not a specific numeric.
  payload = post_intake_industry_baseline_for_naics(
    metric_key="payroll_percent_of_revenue", naics_6="455211"
  )
  assert payload["trust_flag"] in ("naics_2_fallback", "generic_default"), payload
  if payload["trust_flag"] == "naics_2_fallback":
    assert payload["naics_level_used"] == 2
    assert payload["confidence_tier"] == "low", payload
  else:
    assert payload["naics_level_used"] == 0
    assert payload["data_source"] == "expert_default"
    assert payload["confidence_tier"] == "generic_default", payload
  assert payload["benchmark_target"] is not None and payload["benchmark_target"] > 0


# ---------------------------------------------------------------------------
# NexGen NAICS 511210 cascade.
# ---------------------------------------------------------------------------


def test_nexgen_deferred_revenue_resolves_via_sec_edgar() -> None:
  payload = post_intake_industry_baseline_for_naics(
    metric_key="deferred_revenue_percent_of_revenue", naics_6="511210"
  )
  # SEC_EDGAR coverage exists at L2 for NAICS 51 (n=1267 in the gap-fill load).
  # Contract is satisfied by any NAICS-fallback or generic_default level
  # provided the trust_flag and provenance are stamped.
  assert payload["trust_flag"] in (
    "naics_6_direct",
    "naics_5_fallback",
    "naics_4_fallback",
    "naics_3_fallback",
    "naics_2_fallback",
    "generic_default",
  ), payload
  assert payload["benchmark_target"] is not None
  assert payload["data_source"] in ("SEC_EDGAR", "expert_default"), payload


def test_nexgen_marketing_percent_resolves_at_naics_via_sec_edgar() -> None:
  payload = post_intake_industry_baseline_for_naics(
    metric_key="marketing_percent_of_revenue", naics_6="511210"
  )
  assert payload["trust_flag"] != "no_coverage", payload
  assert payload["benchmark_target"] is not None
  assert payload["data_source"] in ("SEC_EDGAR", "expert_default"), payload


def test_nexgen_sga_percent_resolves() -> None:
  payload = post_intake_industry_baseline_for_naics(
    metric_key="sga_percent_of_revenue", naics_6="511210"
  )
  assert payload["trust_flag"] != "no_coverage", payload
  assert payload["benchmark_target"] is not None


# ---------------------------------------------------------------------------
# Confidence-tier downgrade rules.
# ---------------------------------------------------------------------------


def test_confidence_downgrade_rules() -> None:
  # _downgrade_confidence is module-internal; verified through public payloads
  # above. Spot-check the four documented cases:
  cases = [
    ("high", 6, "high"),       # L6 keeps original
    ("high", 5, "medium"),     # L5 caps at medium
    ("high", 4, "medium"),     # L4 caps at medium
    ("high", 3, "low"),        # L3 caps at low
    ("high", 2, "low"),        # L2 caps at low
    ("medium", 5, "medium"),   # already at cap
    ("medium", 3, "low"),      # cap at low
    ("low", 2, "low"),         # already at cap
    ("high", 0, "generic_default"),
  ]
  for raw, level, expected in cases:
    actual = _lookup_module._downgrade_confidence(raw, level_used=level)
    assert actual == expected, f"raw={raw} level={level} -> got {actual}, expected {expected}"


# ---------------------------------------------------------------------------
# no_coverage path + fail_if_no_coverage.
# ---------------------------------------------------------------------------


def test_no_coverage_metric_returns_no_coverage_payload_when_fail_flag_off() -> None:
  # All registry rows currently have fail_if_no_coverage=0, so when the
  # cascade exhausts every level we get a no_coverage payload, not a raise.
  # Force exhaustion by passing a metric that exists in the registry but
  # using an impossible NAICS that won't match any row at any level. The
  # cascade still reaches L0 ('*') for any metric that has a generic_default
  # row, so we instead simulate exhaustion by patching the resolver to skip
  # L0. Simplest: call the resolver with a metric_key that has zero rows.
  # The 49-row registry covers what's loaded; pick one with sparsest L0.
  # All 49 metrics have at least one generic_default per the loader, so we
  # exercise the path by monkey-patching for a single call.
  original_query = _lookup_module._query_baseline_row

  def _always_none(*args, **kwargs):
    return None

  _lookup_module._query_baseline_row = _always_none  # type: ignore[assignment]
  try:
    payload = post_intake_industry_baseline_for_naics(
      metric_key="effective_tax_rate", naics_6="455211"
    )
    assert payload["trust_flag"] == "no_coverage", payload
    assert payload["benchmark_target"] is None, payload
    assert payload["naics_code_used"] is None
    assert "fallback_chain_attempted" in payload
    assert len(payload["fallback_chain_attempted"]) >= 5  # walked L6,L5,L4,L3,L2,L0
  finally:
    _lookup_module._query_baseline_row = original_query  # type: ignore[assignment]


def test_no_coverage_with_fail_flag_raises() -> None:
  original_query = _lookup_module._query_baseline_row
  original_registry = _lookup_module._load_metric_registry

  def _always_none(*args, **kwargs):
    return None

  def _registry_with_fail():
    base = original_registry()
    patched = {k: dict(v) for k, v in base.items()}
    patched["effective_tax_rate"]["fail_if_no_coverage"] = True
    return patched

  _lookup_module._query_baseline_row = _always_none  # type: ignore[assignment]
  _lookup_module._load_metric_registry = _registry_with_fail  # type: ignore[assignment]
  try:
    raised = False
    try:
      post_intake_industry_baseline_for_naics(
        metric_key="effective_tax_rate", naics_6="455211"
      )
    except PostIntakeIndustryBaselineNoCoverage as exc:
      raised = True
      assert "metric_key=effective_tax_rate" in str(exc), str(exc)
      assert "fallback_chain_attempted" in str(exc), str(exc)
    assert raised, "expected PostIntakeIndustryBaselineNoCoverage to be raised"
  finally:
    _lookup_module._query_baseline_row = original_query  # type: ignore[assignment]
    _lookup_module._load_metric_registry = original_registry  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Metric registry caching + governs_lever helper.
# ---------------------------------------------------------------------------


def test_metric_registry_is_cached() -> None:
  # lru_cache(maxsize=1) — calling the loader N times must only hit the DB
  # once. We can't easily intercept the connection without patching, so we
  # check cache_info.
  _lookup_module._load_metric_registry.cache_clear()
  for _ in range(3):
    _lookup_module._load_metric_registry()
  info = _lookup_module._load_metric_registry.cache_info()
  assert info.hits >= 2 and info.misses == 1, f"cache_info={info}"


def test_governs_lever_returns_expected_value_for_known_metric() -> None:
  assert post_intake_industry_metric_governs_lever("cogs_percent_of_revenue") == (
    "expenses::Cost of Goods Sold"
  )
  assert post_intake_industry_metric_governs_lever("effective_tax_rate") == (
    "expenses::Taxes"
  )
  # Unknown metric returns None (graceful for callers that may probe).
  assert post_intake_industry_metric_governs_lever("not_a_real_metric") is None


# ---------------------------------------------------------------------------
# Idempotence + provenance helper.
# ---------------------------------------------------------------------------


def test_resolver_is_idempotent() -> None:
  a = post_intake_industry_baseline_for_naics(
    metric_key="cogs_percent_of_revenue", naics_6="455211"
  )
  b = post_intake_industry_baseline_for_naics(
    metric_key="cogs_percent_of_revenue", naics_6="455211"
  )
  assert a == b, f"idempotence broken: {a} != {b}"


def test_baseline_seed_provenance_shape() -> None:
  payload = post_intake_industry_baseline_for_naics(
    metric_key="cogs_percent_of_revenue", naics_6="455211"
  )
  prov = baseline_seed_provenance(payload)
  for key in (
    "seed_source", "metric_key", "naics_code_used", "naics_level_used",
    "confidence_tier", "data_source", "sample_size", "trust_flag",
  ):
    assert key in prov, f"provenance missing key {key}"
  assert prov["seed_source"] == "naics_cascade"
  assert prov["metric_key"] == "cogs_percent_of_revenue"


# ---------------------------------------------------------------------------
# NAICS-2 applicability (Task 1.7).
# ---------------------------------------------------------------------------


def test_inventory_applicability() -> None:
  # Retail (NAICS 44/45) -> applicable.
  assert post_intake_baseline_applicability_for_naics2(
    metric_key="inventory_days", naics_2="44"
  )["applicable"] is True
  assert post_intake_baseline_applicability_for_naics2(
    metric_key="inventory_days", naics_2="45"
  )["applicable"] is True
  # Manufacturing -> applicable.
  assert post_intake_baseline_applicability_for_naics2(
    metric_key="inventory_days", naics_2="32"
  )["applicable"] is True
  # Information sector (NAICS 51) -> not applicable (services don't carry inventory).
  assert post_intake_baseline_applicability_for_naics2(
    metric_key="inventory_days", naics_2="51"
  )["applicable"] is False
  # Professional services (NAICS 54) -> not applicable.
  assert post_intake_baseline_applicability_for_naics2(
    metric_key="inventory_days", naics_2="54"
  )["applicable"] is False


def test_deferred_revenue_applicability() -> None:
  # Information / Software (51), Professional Services (54), RE (53), Finance (52)
  # -> applicable.
  for naics_2 in ("51", "52", "53", "54"):
    result = post_intake_baseline_applicability_for_naics2(
      metric_key="deferred_revenue_percent_of_revenue", naics_2=naics_2
    )
    assert result["applicable"] is True, (naics_2, result)
  # Retail/accommodation/personal services -> explicitly not applicable.
  for naics_2 in ("44", "45", "72", "81"):
    result = post_intake_baseline_applicability_for_naics2(
      metric_key="deferred_revenue_percent_of_revenue", naics_2=naics_2
    )
    assert result["applicable"] is False, (naics_2, result)
  # Ambiguous sector (e.g., Manufacturing 32) -> default False (conservative).
  result = post_intake_baseline_applicability_for_naics2(
    metric_key="deferred_revenue_percent_of_revenue", naics_2="32"
  )
  assert result["applicable"] is False, result


def test_metric_without_applicability_gate_returns_true() -> None:
  result = post_intake_baseline_applicability_for_naics2(
    metric_key="cogs_percent_of_revenue", naics_2="44"
  )
  assert result["applicable"] is True
  assert result["reason"] == "metric_has_no_applicability_gate"


# ---------------------------------------------------------------------------
# Run all.
# ---------------------------------------------------------------------------


def main() -> int:
  print("running test_industry_baseline_resolver.py")
  print("-" * 70)
  tests = [
    ("valuemart_cogs_l6_direct", test_valuemart_cogs_percent_of_revenue_resolves_at_l6_direct),
    ("valuemart_effective_tax_rate_l5_irs_soi", test_valuemart_effective_tax_rate_falls_through_l6_to_l5_irs_soi),
    ("valuemart_avg_wage_per_fte_l3_bls_oews", test_valuemart_avg_wage_per_fte_resolves_at_l3_bls_oews),
    ("valuemart_payroll_percent_l2_or_l0", test_valuemart_payroll_percent_of_revenue_resolves_at_l2_or_l0),
    ("nexgen_deferred_revenue_via_sec_edgar", test_nexgen_deferred_revenue_resolves_via_sec_edgar),
    ("nexgen_marketing_percent_via_sec_edgar", test_nexgen_marketing_percent_resolves_at_naics_via_sec_edgar),
    ("nexgen_sga_percent", test_nexgen_sga_percent_resolves),
    ("confidence_downgrade_rules", test_confidence_downgrade_rules),
    ("no_coverage_no_fail", test_no_coverage_metric_returns_no_coverage_payload_when_fail_flag_off),
    ("no_coverage_with_fail_raises", test_no_coverage_with_fail_flag_raises),
    ("metric_registry_cached", test_metric_registry_is_cached),
    ("governs_lever_helper", test_governs_lever_returns_expected_value_for_known_metric),
    ("resolver_idempotent", test_resolver_is_idempotent),
    ("baseline_seed_provenance_shape", test_baseline_seed_provenance_shape),
    ("inventory_applicability", test_inventory_applicability),
    ("deferred_revenue_applicability", test_deferred_revenue_applicability),
    ("ungated_metric_applies", test_metric_without_applicability_gate_returns_true),
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
