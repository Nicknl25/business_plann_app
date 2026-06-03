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
from client_intake_and_finmo.post_intake_viability import cohort_bands as _cb  # noqa: E402
from client_intake_and_finmo.post_intake_viability import gates as _gates  # noqa: E402
from client_intake_and_finmo.post_intake_viability import grade as _grade  # noqa: E402
from client_intake_and_finmo.post_intake_viability import policy as _pol  # noqa: E402
from client_intake_and_finmo.post_intake_viability.cohort_bands import HIGHER_BETTER, LOWER_BETTER  # noqa: E402
from client_intake_and_finmo.post_intake_viability import standard as _std  # noqa: E402
from client_intake_and_finmo.post_intake_viability import adapter as _ad  # noqa: E402
from datetime import date as _date  # noqa: E402


def _finmo_from_ebitda(ebitda_list, revenue=100.0):
  """Build a minimal finmo_json (live quarters 1..N) from an EBITDA list."""
  rows = [{"quarter_index": 0, "revenue": 0.0, "ebitda": 0.0}]
  for i, e in enumerate(ebitda_list, start=1):
    rows.append({"quarter_index": i, "revenue": revenue, "ebitda": e})
  return {"quarter_rows": rows}


def _finmo_rich(n=16, rev0=100.0, g=0.05, margin=0.12):
  """Richer finmo_json: growing revenue, fixed EBITDA margin, working-capital
  line items + clean WC deltas, so all four graded constructs are scorable."""
  rows = [{"quarter_index": 0, "revenue": 0.0, "ebitda": 0.0}]
  prev_ar = prev_inv = prev_ap = 0.0
  for i in range(1, n + 1):
    rev = rev0 * ((1 + g) ** (i - 1))
    ar, inv, ap = 0.20 * rev, 0.10 * rev, 0.08 * rev
    rows.append({
      "quarter_index": i, "revenue": rev, "ebitda": margin * rev,
      "accounts_receivable": ar, "inventory": inv, "prepaid_expenses": 0.0,
      "accounts_payable": ap, "deferred_revenue": 0.0,
      "changes_in_current_assets": -((ar - prev_ar) + (inv - prev_inv)),
      "changes_in_current_liabilities": (ap - prev_ap),
    })
    prev_ar, prev_inv, prev_ap = ar, inv, ap
  return {"quarter_rows": rows}


# Synthetic cohort bands (SMB-ish, deterministic) for grade tests.
_BANDS = {
  "ebitda_margin_q": {"available": True, "p25": -0.04, "p50": 0.05, "p75": 0.10,
                       "direction": HIGHER_BETTER, "naics_level_used": 6},
  "revenue_growth_q": {"available": True, "p25": -0.05, "p50": 0.02, "p75": 0.10,
                       "direction": HIGHER_BETTER, "naics_level_used": 6},
  "current_assets_minus_cash_to_revenue": {"available": True, "p25": 0.05, "p50": 0.10, "p75": 0.20,
                                           "direction": LOWER_BETTER, "naics_level_used": 6},
  "current_liabilities_to_revenue": {"available": True, "p25": 0.03, "p50": 0.06, "p75": 0.10,
                                     "direction": HIGHER_BETTER, "naics_level_used": 6},
}


def _load_env_once() -> None:
  env = os.path.join(_ROOT, ".env")
  if not os.path.exists(env):
    return
  for line in open(env, encoding="utf-8-sig"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


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


# ---------------------------------------------------------------------------
# Unit 4 (§5) — cohort band resolution for graded constructs.
# ---------------------------------------------------------------------------


def test_band_to_dict_none_is_unavailable_not_faked() -> None:
  d = _cb._band_to_dict(None, "ebitda_margin_q")
  assert d["available"] is False
  assert d["p25"] is None and d["p50"] is None and d["p75"] is None
  assert d["direction"] == _cb.HIGHER_BETTER


def test_construct_cohort_reference_mapping_columns_known() -> None:
  # Every referenced column must be a registered resolver column.
  for cols in _cb.CONSTRUCT_COHORT_REFERENCES.values():
    for col in cols:
      assert col in _cbr._KNOWN_METRIC_COLUMNS, f"{col} not a known resolver column"
      assert col in _cb.VIABILITY_METRIC_DIRECTIONS


def test_directions_orientation() -> None:
  assert _cb.VIABILITY_METRIC_DIRECTIONS["ebitda_margin_q"] == _cb.HIGHER_BETTER
  assert _cb.VIABILITY_METRIC_DIRECTIONS["current_assets_minus_cash_to_revenue"] == _cb.LOWER_BETTER


def test_resolve_viability_bands_live_best_effort() -> None:
  # Best-effort live check against the DB. Skips (soft pass) when the DB is
  # unreachable so the suite still runs without a DB; asserts band sanity
  # when it IS reachable. (Live resolution was confirmed manually in Unit 1.)
  _load_env_once()
  bands = _cb.resolve_viability_bands(
    {"naics_6": "311811", "target_annual_revenue": 1500000, "stage": "operational"}
  )
  assert set(bands.keys()) == set(_cb.VIABILITY_METRIC_DIRECTIONS.keys())
  available = [b for b in bands.values() if b["available"]]
  if not available:
    print("    (skipped live band asserts — DB unreachable)")
    return
  for b in available:
    assert b["p25"] is not None and b["p50"] is not None and b["p75"] is not None
    assert b["p25"] <= b["p50"] <= b["p75"], f"band not ordered: {b}"
    assert b["firm_count"] is not None and b["firm_count"] >= 2


# ---------------------------------------------------------------------------
# Unit 5 (§3, §4.1b, §4.3, §7) — Tier 2 gates.
# ---------------------------------------------------------------------------


def test_gate_a_deadline_age_anchoring() -> None:
  d = _gates.gate_a_deadline_plan_quarter
  assert d(business_age_quarters=0) == 10           # brand-new startup: full Q10
  assert d(business_age_quarters=5) == 5            # 5q elapsed -> plan-Q5
  assert d(business_age_quarters=9) == 2            # past-ish: floored to 2q grace
  assert d(business_age_quarters=20) == 2           # well past: grace floor
  assert d(business_age_quarters=0, distress=True) == 14  # +4 under turnaround


def test_gate_a_pass_when_sustained_positive_by_deadline() -> None:
  rows = _con.live_quarter_rows(_finmo_from_ebitda(
    [-20, -15, -10, -5, -2, 2, 6, 10, 14, 18] + [20] * 10))
  g = _gates.evaluate_gate_a(rows, business_age_quarters=0)
  assert g["passed"] is True
  assert g["breakeven_plan_q"] is not None and g["breakeven_plan_q"] <= 10


def test_gate_a_fail_when_never_positive_by_deadline() -> None:
  rows = _con.live_quarter_rows(_finmo_from_ebitda([-5] * 20))
  g = _gates.evaluate_gate_a(rows, business_age_quarters=0)
  assert g["passed"] is False
  assert g["evaluable"] is True  # data present, genuinely failed (not indeterminate)


def test_gate_a_cannot_fire_before_business_q4() -> None:
  # Positive from q1; breakeven must be detected at business-Q4, never earlier.
  rows = _con.live_quarter_rows(_finmo_from_ebitda([5] * 20))
  g = _gates.evaluate_gate_a(rows, business_age_quarters=0)
  assert g["breakeven_plan_q"] == 4, g


def test_gate_a_distress_extends_deadline() -> None:
  # Sustained positive first reached at plan-Q12 — fails at Q10, passes at Q14.
  ebitda = [-5] * 11 + [50] * 9  # trailing-4q sum crosses 0 around q12-13
  rows = _con.live_quarter_rows(_finmo_from_ebitda(ebitda))
  base = _gates.evaluate_gate_a(rows, business_age_quarters=0, distress=False)
  dist = _gates.evaluate_gate_a(rows, business_age_quarters=0, distress=True)
  assert base["passed"] is False
  assert dist["passed"] is True and dist["deadline_plan_q"] == 14


def test_gate_b_cumulative() -> None:
  rows_pos = _con.live_quarter_rows(_finmo_from_ebitda([10] * 20))
  rows_neg = _con.live_quarter_rows(_finmo_from_ebitda([-10] * 20))
  assert _gates.evaluate_gate_b(rows_pos)["passed"] is True
  assert _gates.evaluate_gate_b(rows_neg)["passed"] is False


def test_gate_b_posture_independent() -> None:
  # evaluate_gates with distress must not change Gate B.
  fj = _finmo_from_ebitda([-10] * 20)
  g0 = _gates.evaluate_gates(fj, business_age_quarters=0, distress=False)
  g1 = _gates.evaluate_gates(fj, business_age_quarters=0, distress=True)
  assert g0["gate_b"]["passed"] == g1["gate_b"]["passed"] is False


def test_evaluate_gates_all_pass() -> None:
  fj = _finmo_from_ebitda([-20, -15, -10, -5, -2, 2, 6, 10, 14, 18] + [20] * 10)
  g = _gates.evaluate_gates(fj, business_age_quarters=0)
  assert g["gate_a"]["passed"] and g["gate_b"]["passed"] and g["all_pass"]


# ---------------------------------------------------------------------------
# Unit 6 (§3, §5, §6, §7) — Tier 1 grade.
# ---------------------------------------------------------------------------


def test_health_percentile_anchors_and_direction() -> None:
  hp = _grade._health_percentile
  assert _approx(hp(0.05, -0.04, 0.05, 0.10, HIGHER_BETTER), 0.50)
  assert _approx(hp(-0.04, -0.04, 0.05, 0.10, HIGHER_BETTER), 0.25)
  assert _approx(hp(0.10, -0.04, 0.05, 0.10, HIGHER_BETTER), 0.75)
  # lower-better: a value at the cohort's p25 (low) is HEALTHY -> high health.
  assert _approx(hp(0.05, 0.05, 0.10, 0.20, LOWER_BETTER), 0.75)


def test_level_score_from_health_curve() -> None:
  f = _grade._level_score_from_health
  assert _approx(f(0.50), 1.0)
  assert _approx(f(0.75), 1.0)   # capped
  assert _approx(f(0.25), 0.5)   # clears p25 -> 0.5
  assert _approx(f(0.375), 0.75)
  assert _approx(f(0.0), 0.0)


def test_grade_strong_beats_weak() -> None:
  strong = _finmo_rich(n=16, rev0=100, g=0.08, margin=0.15)   # above p75 margin, strong growth
  weak = _finmo_rich(n=16, rev0=100, g=-0.02, margin=-0.06)   # below p25 margin, shrinking
  gs = _grade.grade(strong, _BANDS, stage="operational", deadline_plan_q=10)
  gw = _grade.grade(weak, _BANDS, stage="operational", deadline_plan_q=10)
  assert gs["overall_score"] is not None and gw["overall_score"] is not None
  assert 0.0 <= gw["overall_score"] <= gs["overall_score"] <= 1.0
  assert gs["overall_score"] > gw["overall_score"]


def test_grade_ebitda_ramp_is_trajectory_only() -> None:
  g = _grade.grade(_finmo_rich(), _BANDS, stage="startup", deadline_plan_q=10)
  assert g["per_construct"]["ebitda_ramp"]["level_score"] is None
  assert g["per_construct"]["ebitda_ramp"]["trajectory_score"] is not None


def test_grade_unavailable_band_drops_level_not_crash() -> None:
  bands = {k: dict(v) for k, v in _BANDS.items()}
  bands["ebitda_margin_q"] = {"available": False, "p25": None, "p50": None, "p75": None,
                              "direction": HIGHER_BETTER}
  g = _grade.grade(_finmo_rich(), bands, stage="operational", deadline_plan_q=10)
  # operating_cash_proxy + ebitda_ramp reference ebitda_margin_q -> level drops,
  # but the grade still computes (no crash) from the remaining constructs.
  assert g["overall_score"] is not None
  assert g["per_construct"]["operating_cash_proxy"]["level_score"] is None


def test_grade_distress_relaxes_convergence_bar() -> None:
  # A below-target, slowly-improving firm: distress lowers the convergence
  # target, so the trajectory/overall score is >= the non-distress score.
  fj = _finmo_rich(n=16, rev0=100, g=0.01, margin=-0.02)
  base = _grade.grade(fj, _BANDS, stage="startup", deadline_plan_q=10, distress=False)
  dist = _grade.grade(fj, _BANDS, stage="startup", deadline_plan_q=10, distress=True)
  assert dist["overall_score"] >= base["overall_score"]


# ---------------------------------------------------------------------------
# Unit 7+8 (§3, §7, §8) — verdict orchestrator + posture.
# ---------------------------------------------------------------------------


def _with_bands(bands):
  """Context-managerish helper: patch standard.resolve_viability_bands."""
  orig = _std.resolve_viability_bands
  _std.resolve_viability_bands = lambda profile: dict(bands)
  return orig


def test_verdict_non_viable_when_gate_fails() -> None:
  fj = _finmo_from_ebitda([-5] * 20)  # never breaks even, cumulative < 0
  v = _std.evaluate_viability(fj, business_age_months=0,
                              business_profile={"naics_6": "311811", "target_annual_revenue": 1.5e6})
  assert v["verdict"] == _std.VERDICT_NON_VIABLE
  assert v["viable"] is False
  assert v["grade"] is not None  # grade still computed for the refine signal


def test_verdict_pass_when_gates_clear_and_grade_strong() -> None:
  orig = _with_bands(_BANDS)
  try:
    fj = _finmo_rich(n=16, rev0=100, g=0.08, margin=0.15)
    v = _std.evaluate_viability(fj, business_age_months=48,  # operational
                                business_profile={"naics_6": "311811", "target_annual_revenue": 1.5e6})
    assert v["viable"] is True
    assert v["tier1_score"] is not None and v["tier1_score"] >= v["pass_refine_threshold"]
    assert v["verdict"] == _std.VERDICT_PASS
    assert v["stage"] == "operational"
  finally:
    _std.resolve_viability_bands = orig


def test_verdict_refine_when_viable_but_ungraded() -> None:
  # Gates clear but no naics -> no bands -> tier1 None -> refine (never silent pass).
  fj = _finmo_rich(n=16, rev0=100, g=0.04, margin=0.10)
  v = _std.evaluate_viability(fj, business_age_months=48, business_profile={})
  assert v["viable"] is True
  assert v["tier1_score"] is None
  assert v["verdict"] == _std.VERDICT_REFINE
  assert any("tier1_ungraded" in n for n in v["notes"])


def test_posture_distress_changes_gate_a_verdict() -> None:
  # Breakeven first sustained ~Q12: fails Gate A at Q10 (non_viable) but the
  # +4q distress deadline (Q14) lets it through. Gate B passes both (cum>0).
  fj = _finmo_from_ebitda([-5] * 11 + [50] * 9)
  base = _std.evaluate_viability(fj, business_age_months=0, business_profile={})
  dist = _std.evaluate_viability(fj, business_age_months=0, business_profile={},
                                 explicit_distress_context=True)
  assert base["verdict"] == _std.VERDICT_NON_VIABLE  # gate A misses Q10
  assert dist["viable"] is True                      # distress extends to Q14
  assert dist["gates"]["gate_b"]["passed"] is True   # gate B firm in both


def test_stage_is_age_derived() -> None:
  v_startup = _std.evaluate_viability(_finmo_rich(), business_age_months=6, business_profile={})
  v_oper = _std.evaluate_viability(_finmo_rich(), business_age_months=48, business_profile={})
  assert v_startup["stage"] == "startup"
  assert v_oper["stage"] == "operational"


def test_age_unavailable_defaults_and_notes() -> None:
  v = _std.evaluate_viability(_finmo_rich(), business_profile={})  # no age, no start_date
  assert v["stage"] == "startup"
  assert any("business_age_unavailable" in n for n in v["notes"])


# ---------------------------------------------------------------------------
# Unit 9 (§9) — pipeline adapter + wiring.
# ---------------------------------------------------------------------------


def test_adapter_parse_start_date_formats() -> None:
  assert _ad._parse_start_date("06/19/2024") == _date(2024, 6, 19)
  assert _ad._parse_start_date("2024-06-19") == _date(2024, 6, 19)
  assert _ad._parse_start_date("") is None
  assert _ad._parse_start_date(None) is None


def test_adapter_distress_detection() -> None:
  assert _ad._is_distress({"planning_mode": "turnaround"}) is True
  assert _ad._is_distress({"planning_mode_reason": "app_classified_distress_case"}) is True
  assert _ad._is_distress({"explicit_distress_context": True}) is True
  assert _ad._is_distress({"planning_mode": "normalize"}) is False
  assert _ad._is_distress({}) is False


def test_adapter_extract_naics_from_nests() -> None:
  assert _ad._extract_naics({}, {"business_naics_6": "311811"}, {}) == "311811"
  assert _ad._extract_naics({}, {}, {"business_naics_6": "722511"}) == "722511"
  assert _ad._extract_naics({"operating_model_json": {"business_naics_6": "448140"}}, {}, {}) == "448140"
  assert _ad._extract_naics({}, {}, {}) is None


def test_adapter_never_raises_on_garbage() -> None:
  r = _ad.evaluate_run_viability(finmo_json="not a dict", draft=None, planning_run_json=None)
  assert isinstance(r, dict) and "verdict" in r  # error-wrapped, not an exception


def test_adapter_produces_coherent_verdict() -> None:
  fj = _finmo_rich(n=16, rev0=100, g=0.05, margin=0.12)
  r = _ad.evaluate_run_viability(
    finmo_json=fj,
    draft={"business_start_date": "06/19/2022"},
    planning_run_json={"planning_mode": "rebalance"},
    as_of=_date(2026, 6, 2),
  )
  assert r["verdict"] in (_std.VERDICT_PASS, _std.VERDICT_REFINE, _std.VERDICT_NON_VIABLE)
  assert r["stage"] in ("startup", "early", "operational", "mature")


def test_real_sunny_finmo_flows_to_verdict() -> None:
  """The original Fix #1 failing case: the standard must produce a COHERENT
  verdict on Sunny's real (deeply loss-making, flat-revenue) finmo_json —
  non_viable is the expected, acceptable outcome. Best-effort (needs DB)."""
  _load_env_once()
  try:
    import json as _json
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
    conn = get_mysql_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
      "SELECT finmo_json, planning_run_json, model_input_json, business_start_date "
      "FROM intake_consult_drafts WHERE business_name LIKE %s AND finmo_json IS NOT NULL "
      "ORDER BY planning_run_started_at DESC LIMIT 1",
      ("%Sunny%",),
    )
    row = cur.fetchone()
    conn.close()
  except Exception as exc:
    print(f"    (skipped — DB unreachable: {type(exc).__name__})")
    return
  if not row:
    print("    (skipped — no Sunny draft with finmo_json)")
    return
  r = _ad.evaluate_run_viability(
    finmo_json=_json.loads(row["finmo_json"]),
    draft={"business_start_date": row["business_start_date"]},
    model_input_json=_json.loads(row["model_input_json"]) if row.get("model_input_json") else {},
    planning_run_json=_json.loads(row["planning_run_json"]) if row.get("planning_run_json") else {},
    as_of=_date(2026, 6, 2),
  )
  assert r["verdict"] in (_std.VERDICT_PASS, _std.VERDICT_REFINE, _std.VERDICT_NON_VIABLE), r
  # Sunny is deeply loss-making with flat revenue -> gates must fail it.
  assert r["verdict"] == _std.VERDICT_NON_VIABLE, r
  print(f"    Sunny real finmo -> verdict={r['verdict']} stage={r['stage']} "
        f"gateA={r['gates']['gate_a']['passed']} gateB={r['gates']['gate_b']['passed']}")


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
    ("u4_band_to_dict_none_unavailable", test_band_to_dict_none_is_unavailable_not_faked),
    ("u4_construct_refs_columns_known", test_construct_cohort_reference_mapping_columns_known),
    ("u4_directions_orientation", test_directions_orientation),
    ("u4_resolve_bands_live_best_effort", test_resolve_viability_bands_live_best_effort),
    ("u5_gate_a_deadline_age_anchoring", test_gate_a_deadline_age_anchoring),
    ("u5_gate_a_pass_sustained", test_gate_a_pass_when_sustained_positive_by_deadline),
    ("u5_gate_a_fail_never_positive", test_gate_a_fail_when_never_positive_by_deadline),
    ("u5_gate_a_q4_floor", test_gate_a_cannot_fire_before_business_q4),
    ("u5_gate_a_distress_extends", test_gate_a_distress_extends_deadline),
    ("u5_gate_b_cumulative", test_gate_b_cumulative),
    ("u5_gate_b_posture_independent", test_gate_b_posture_independent),
    ("u5_evaluate_gates_all_pass", test_evaluate_gates_all_pass),
    ("u6_health_percentile_anchors", test_health_percentile_anchors_and_direction),
    ("u6_level_score_curve", test_level_score_from_health_curve),
    ("u6_grade_strong_beats_weak", test_grade_strong_beats_weak),
    ("u6_ebitda_ramp_trajectory_only", test_grade_ebitda_ramp_is_trajectory_only),
    ("u6_unavailable_band_drops_level", test_grade_unavailable_band_drops_level_not_crash),
    ("u6_distress_relaxes_bar", test_grade_distress_relaxes_convergence_bar),
    ("u7_verdict_non_viable_gate_fail", test_verdict_non_viable_when_gate_fails),
    ("u7_verdict_pass_strong", test_verdict_pass_when_gates_clear_and_grade_strong),
    ("u7_verdict_refine_ungraded", test_verdict_refine_when_viable_but_ungraded),
    ("u8_posture_distress_changes_verdict", test_posture_distress_changes_gate_a_verdict),
    ("u7_stage_age_derived", test_stage_is_age_derived),
    ("u7_age_unavailable_defaults", test_age_unavailable_defaults_and_notes),
    ("u9_adapter_parse_start_date", test_adapter_parse_start_date_formats),
    ("u9_adapter_distress_detection", test_adapter_distress_detection),
    ("u9_adapter_extract_naics", test_adapter_extract_naics_from_nests),
    ("u9_adapter_never_raises", test_adapter_never_raises_on_garbage),
    ("u9_adapter_coherent_verdict", test_adapter_produces_coherent_verdict),
    ("u9_real_sunny_flows_to_verdict", test_real_sunny_finmo_flows_to_verdict),
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
