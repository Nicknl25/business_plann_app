"""COHERENCE STRUCTURAL EVALUATOR — the closed-form v2 gate.

One arithmetic core answers one question at the Q11 mature state:
"can the engine author a passing plan from this structure?" — the five
binding inequalities (C1-C5), each threshold read from the executive's
margin-band judgment with doctrine-constant fallbacks.

THE VERDICT IS AN EXISTS-AUTHORABLE QUESTION. The engine target-seeks
the judged band: growth is its free authority (bounded by the 7% QoQ
authorable fence), variable costs scale as percent-of-revenue, and the
fixed stack dilutes as revenue grows — so EBITDA margin is MONOTONE
IMPROVING in revenue. Evaluating at the fence point is therefore
equivalent to asking whether ANY authorable Q11 clears the band floor:
  - closed-form PASS at the fence  => an authorable passing Q11 exists
  - closed-form FAIL at the fence  => no authorable Q11 can clear it,
    and the FAIL is stable (monotonicity — more conservative growth is
    strictly worse). This is what makes surfacing a FAIL immediately
    safe: it cannot flip on the same configuration.

BASIS DOCTRINE (fitted against the 7-run fleet ground truth):
  - Q1 revenue: the engine's own presence-keyed anchor — stated
    current_revenue first (all seven fleet drafts land Q1 = stated/4),
    then the Year-1 projection, then the capacity-driven ceiling.
  - Variable costs (COGS, marketing, G&A) are PERCENT OF REVENUE —
    the engine's own treatment (searcher._base_levels basis). Flat
    dollars was the v1 error that false-passed Understory at the fence.
  - G&A percent comes from other_opex_absolute (the annual contract
    field intake always writes); the monthly*12 fallback serves
    pre-contract drafts only.
  - Payroll + owner comp are FLAT dollars (the engine stages payroll a
    few percent upward by Q11; flat-at-stated is the mild-generous
    side of that and is covered by the fence-verdict slack).
  - Interest/depreciation for C5 are the advisory SBA arithmetic
    (rate constants below — the lender's seat, never judged).

CONSERVATISM CONTRACT (the Phase-0 fidelity claim): computed on the
engine's OWN basis (model_input base levels + landed revenue), this
arithmetic never overstates the engine's landed Q11 EBITDA margin by
more than ~1pp — the engine's cost percents drift favorably by Q11, the
closed form holds them at the Q1 basis. The closed form is a floor, not
a promise.
"""

from __future__ import annotations

import re as _re

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_headcount.deterministic_revenue_proposer import (
  _DEFAULT_PRICE_INFLATION_QOQ as _PROPOSER_PRICE_INFLATION_QOQ,
)


# Q1 -> Q11 authorable growth ceiling: ten quarters at the model's own
# 7% QoQ cap. The engine may land anywhere at or below this; the
# verdict evaluates at the ceiling (exists-authorable, see module doc).
GROWTH_FENCE_Q11 = 1.07 ** 10

# CW-022 #101 (A3, Nick-approved deal breaker): THE STATED-CAPACITY WALL.
# The fence is an authorable-GROWTH ceiling, not a throughput licence: a
# Q11 point that needs more units than the client's stated capacity can
# physically produce is not authorable from THIS operation - Fetch & Fluff
# turn 96 PASSED at $96,390/yr against a 30-grooms/wk x $45 x 52 =
# $70,200/yr ceiling (137% of capacity) and the plan certified numbers
# the client had said she cannot produce. Every coherence basis (fence,
# judged, corner, walk) therefore caps its growth multiple at the
# PHYSICAL-CEILING MULTIPLE = (stated capacity x price x periods at 100%
# utilization, on the engine's own Q1->Q11 price path) / revenue anchor.
# The price path is the deterministic proposer's own 1%/q drift - the
# same currency the judged multiple is read in - so the wall bounds
# THROUGHPUT (units), never the price the engine already authors.
# Non-unit-driven models (no priced products) carry no wall; a consented
# capacity move re-lands ops and raises the wall by construction.
PRICE_PATH_Q11 = (1.0 + _PROPOSER_PRICE_INFLATION_QOQ) ** 10

# Advisory debt arithmetic (the lender's seat — never judged).
SBA_ANNUAL_RATE = 0.105
COVERAGE_FLOOR = 1.5

# Doctrine-constant fallbacks when the margin-band judgment is absent
# (a draft authored before the judgment existed). The judged values
# always win when present.
FALLBACK_GM_FLOOR = 0.20
FALLBACK_BURDEN_MAX = 0.65
FALLBACK_NI_FLOOR = 0.02
FALLBACK_BAND_LOW = 0.0


def _f(value: Any, default: float = 0.0) -> float:
  try:
    if value in (None, ""):
      return default
    number = float(value)
  except (TypeError, ValueError):
    return default
  if number != number:  # NaN
    return default
  return number


def _opt(value: Any) -> Optional[float]:
  try:
    if value in (None, ""):
      return None
    number = float(value)
  except (TypeError, ValueError):
    return None
  if number != number:
    return None
  return number


@dataclass
class StructuralBasis:
  """The Q11 evaluation basis. All quarterly dollars; percents of
  revenue for the variable stack."""
  q1_revenue_quarterly: float
  cogs_pct: float
  payroll_quarterly: float
  rent_quarterly: float
  gna_pct: float
  marketing_pct: float
  interest_quarterly: float = 0.0
  depreciation_quarterly: float = 0.0
  growth_to_q11: float = GROWTH_FENCE_Q11
  # provenance notes for traces / phrasing payloads
  notes: Dict[str, Any] = field(default_factory=dict)

  def q11_revenue(self) -> float:
    return self.q1_revenue_quarterly * self.growth_to_q11


@dataclass
class Thresholds:
  gm_floor: float
  burden_max: float
  band_low: float
  ni_floor: float
  band_high: Optional[float] = None
  judged: bool = False


def thresholds_from_margin_band(margin_band: Optional[Dict[str, Any]]) -> Thresholds:
  mb = margin_band if isinstance(margin_band, dict) else {}
  q11 = mb.get("q11") if isinstance(mb.get("q11"), dict) else {}
  gm = _opt(mb.get("gross_margin_floor_q11"))
  burden = _opt(mb.get("fixed_cost_burden_max_q11"))
  ni = _opt(mb.get("ni_margin_floor_q11"))
  low = _opt(q11.get("low"))
  high = _opt(q11.get("high"))
  return Thresholds(
    gm_floor=gm if gm is not None else FALLBACK_GM_FLOOR,
    burden_max=burden if burden is not None else FALLBACK_BURDEN_MAX,
    band_low=low if low is not None else FALLBACK_BAND_LOW,
    ni_floor=ni if ni is not None else FALLBACK_NI_FLOOR,
    band_high=high,
    judged=bool(mb),
  )


def evaluate_structural(basis: StructuralBasis, thresholds: Thresholds) -> Dict[str, Any]:
  """The five binding inequalities at the Q11 point of `basis`.

  Returns verdict + per-check detail + the dollar gap per mature
  quarter (`gap = band_low_floor - ebitda` when positive) — the number
  the coherence conversation works on.
  """
  rev = basis.q11_revenue()
  if rev <= 0:
    return {
      "passed": False,
      "checks": {"no_revenue": {"passed": False}},
      "failed": ["no_revenue"],
      "gap_quarterly": None,
      "q11": {"revenue": 0.0},
    }
  gm = 1.0 - basis.cogs_pct
  cogs = rev * basis.cogs_pct
  gna = rev * basis.gna_pct
  marketing = rev * basis.marketing_pct
  fixed = basis.payroll_quarterly + basis.rent_quarterly + gna
  ebitda = rev * gm - fixed - marketing
  ebitda_margin = ebitda / rev
  burden = fixed / rev
  ni = ebitda - basis.interest_quarterly - basis.depreciation_quarterly
  ni_margin = ni / rev

  checks = {
    "gross_margin": {
      "passed": gm >= thresholds.gm_floor,
      "value": gm, "threshold": thresholds.gm_floor,
    },
    "fixed_cost_burden": {
      "passed": burden <= thresholds.burden_max,
      "value": burden, "threshold": thresholds.burden_max,
    },
    "ebitda_positive": {
      "passed": ebitda >= 0.0,
      "value": ebitda, "threshold": 0.0,
    },
    "ebitda_band_low": {
      "passed": ebitda_margin >= thresholds.band_low,
      "value": ebitda_margin, "threshold": thresholds.band_low,
    },
    "ni_floor": {
      "passed": ni_margin >= thresholds.ni_floor,
      "value": ni_margin, "threshold": thresholds.ni_floor,
    },
  }
  failed = [name for name, c in checks.items() if not c["passed"]]
  floor_dollars = thresholds.band_low * rev
  # The gap is the dollars-per-quarter of change needed on the BINDING
  # constraint — the max shortfall across every failing check, not just
  # the band floor (a config can clear the band while fixed-cost burden
  # still binds; the walk must keep going until ALL five hold).
  shortfalls = []
  if not checks["ebitda_band_low"]["passed"]:
    shortfalls.append(floor_dollars - ebitda)
  if not checks["ebitda_positive"]["passed"]:
    shortfalls.append(-ebitda)
  if not checks["fixed_cost_burden"]["passed"]:
    shortfalls.append((burden - thresholds.burden_max) * rev)
  if not checks["ni_floor"]["passed"]:
    shortfalls.append((thresholds.ni_floor - ni_margin) * rev)
  if not checks["gross_margin"]["passed"]:
    shortfalls.append((thresholds.gm_floor - gm) * rev)
  gap = max(0.0, max(shortfalls) if shortfalls else 0.0)
  return {
    "passed": not failed,
    "checks": checks,
    "failed": failed,
    "gap_quarterly": round(gap, 2),
    "q11": {
      "revenue": round(rev, 2),
      "cogs": round(cogs, 2),
      "payroll": round(basis.payroll_quarterly, 2),
      "rent": round(basis.rent_quarterly, 2),
      "gna": round(gna, 2),
      "marketing": round(marketing, 2),
      "ebitda": round(ebitda, 2),
      "ebitda_margin": round(ebitda_margin, 6),
      "ni_margin": round(ni_margin, 6),
      "band_low_floor_dollars": round(floor_dollars, 2),
    },
  }


def growth_multiple_from_judged(
  judged_growth: Optional[Dict[str, Any]],
  *,
  ops_json: Optional[Dict[str, Any]] = None,
  to_quarter: int = 11,
) -> Optional[float]:
  """Q1→Q<to_quarter> revenue multiple by CALLING the engine's own
  deterministic revenue proposer with the judged rates and the intake
  ops line reference, and reading the multiple off its own output.

  NOT a mirror: the proposer composes the growth taper WITH a
  utilization ramp (stated → mature by Q11) and price drift — the
  taper-only mirror understated Meridian ×1.184 vs the engine's ×1.392
  and flipped its verdict. Single source of truth, zero drift by
  construction; the multiple is anchor-scale-invariant so no revenue
  anchor is needed.

  Returns None when the judgment or a usable line reference is absent —
  callers fall back to the authorable fence, never to a guess."""
  jg = judged_growth if isinstance(judged_growth, dict) else {}
  qs = _opt(jg.get("qoq_start"))
  qe = _opt(jg.get("qoq_end"))
  if qs is None or qe is None:
    return None
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (
    _build_lines_of_business_slice,
  )
  from client_intake_and_finmo.post_intake_headcount.deterministic_revenue_proposer import (
    propose_revenue_drivers_deterministic,
  )
  reference = _build_lines_of_business_slice(ops_json)
  if not reference:
    return None
  result = propose_revenue_drivers_deterministic(
    current_revenue_reference=reference,
    qoq_start=qs,
    qoq_end=qe,
  )
  if not result.get("ok"):
    return None
  q1_total = 0.0
  qn_total = 0.0
  for line in ((result.get("drivers") or {}).get("lines_of_business") or []):
    by_q = {}
    for q in (line.get("quarters") or []):
      try:
        by_q[int(q.get("q"))] = q
      except (TypeError, ValueError):
        continue
    def _rev(entry: Optional[Dict[str, Any]]) -> float:
      if not isinstance(entry, dict):
        return 0.0
      return (
        _f(entry.get("capacity_units_per_period"))
        * _f(entry.get("unit_price"))
        * _f(entry.get("utilization_rate"))
      )
    q1_total += _rev(by_q.get(1))
    qn_total += _rev(by_q.get(int(to_quarter)))
  if q1_total <= 0 or qn_total <= 0:
    return None
  return qn_total / q1_total


# ------------------------------------------------------------------ capacity wall

def ops_implied_and_ceiling(ops_json: Optional[Dict[str, Any]]) -> Tuple[float, float]:
  """(CW-022 #2 / #101) The operation's own annual revenue arithmetic:
  implied = sum(price x capacity x periods x utilization) and the
  physical ceiling = the same at utilization 1.0. Zero when the model
  carries no unit-driven products (non-unit businesses skip the check).
  ONE arithmetic for the gate's anchor hold and the growth wall."""
  implied = 0.0
  ceiling = 0.0
  for lob in (ops_json or {}).get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    for p in lob.get("products") or []:
      if not isinstance(p, dict):
        continue
      price = _f(p.get("unit_price"))
      cap = _f(p.get("units_per_period_capacity"))
      periods = _f(p.get("operating_periods_per_year")) or 12.0
      util = _f(p.get("utilization_rate"))
      util = util if 0.0 < util <= 1.0 else 1.0
      if price > 0 and cap > 0:
        implied += price * cap * periods * util
        ceiling += price * cap * periods
  return implied, ceiling


def capacity_growth_ceiling(
  ops_json: Optional[Dict[str, Any]],
  annual_revenue_anchor: float,
) -> Optional[float]:
  """The Q1->Q11 revenue multiple at which the stated operation is
  flat-out: physical ceiling x the engine's own price path / anchor.
  None when the model has no unit-driven products or no anchor (no
  wall to apply); never below 1.0 (an anchor already above the ceiling
  is the anchor hold's job, not this wall's)."""
  anchor = _f(annual_revenue_anchor)
  if anchor <= 0:
    return None
  _implied, ceiling = ops_implied_and_ceiling(ops_json)
  if ceiling <= 0:
    return None
  return max(1.0, (ceiling * PRICE_PATH_Q11) / anchor)


# ------------------------------------------------------------------ bases

def basis_from_intake(
  *,
  financials_json: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  growth_to_q11: float = GROWTH_FENCE_Q11,
) -> Optional[StructuralBasis]:
  """The live intake basis (see module doctrine). Returns None when no
  revenue source is usable — the evaluator has nothing to say yet."""
  fin = financials_json if isinstance(financials_json, dict) else {}
  notes: Dict[str, Any] = {}

  ann_rev = _f(fin.get("current_revenue"))
  if ann_rev > 0:
    notes["revenue_source"] = "current_revenue"
  else:
    year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
    ann_rev = _f(year1.get("company_revenue_total_year1")) or _f(year1.get("revenue_total_year1"))
    if ann_rev > 0:
      notes["revenue_source"] = "year1_projection"
    else:
      from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (
        capacity_driven_annual_revenue,
      )
      ann_rev = _f(capacity_driven_annual_revenue(ops_json=ops_json))
      if ann_rev > 0:
        notes["revenue_source"] = "capacity_driven"
  if ann_rev <= 0:
    return None

  cogs_pct = _opt(fin.get("cogs_percent_of_revenue"))
  if cogs_pct is None:
    cogs = _f(fin.get("current_cogs"))
    cogs_pct = cogs / ann_rev if ann_rev else 0.0
  cogs_pct = max(0.0, min(2.0, float(cogs_pct)))

  # Payroll truth is the People-owned summing point (7aa64c5): key people +
  # rest-of-team, stamped as baseline_payroll_year1 with people-derived
  # provenance, plus any client-approved coherence delta (payroll_adjustment).
  # The financials echo fields are LEGACY FALLBACK only — they proved
  # clobberable (Harborline CW-001: an echo-patch zeroed both while the
  # baseline stamp survived).
  payroll = _f(fin.get("baseline_payroll_year1"))
  payroll_source = "people_baseline"
  if payroll <= 0:
    payroll = _f(fin.get("current_payroll")) or _f(fin.get("payroll_total_year1"))
    payroll_source = "financials_echo_legacy"
  else:
    payroll = max(0.0, payroll + _f(fin.get("payroll_adjustment")))
  # Owner comp is NON-ADDITIVE when an owner/principal is already among the
  # people roles: their wage is inside the baseline, so adding owner comp on
  # top double-counts the same dollars (each dollar exactly once). Owner comp
  # then informs cash modeling only.
  owner_comp_annual = _f(fin.get("owner_compensation")) * 12.0
  roles = fin.get("payroll_basis_people_roles") or []
  owner_in_roles = any(
    _re.search(r"owner|principal|founder|managing|partner", str(r.get("role_title") or ""), _re.I)
    for r in roles
    if isinstance(r, dict)
  )
  owner_comp_additive = 0.0 if owner_in_roles else owner_comp_annual
  notes["payroll_basis"] = {
    "annual": payroll,
    "source": payroll_source,
    "owner_comp_annual": owner_comp_annual,
    "owner_in_roles": owner_in_roles,
    "owner_comp_additive": owner_comp_additive,
  }

  gna_annual = _f(fin.get("other_opex_absolute"))
  if gna_annual <= 0:
    gna_annual = _f(fin.get("other_operating_expense")) * 12.0
    notes["gna_source"] = "monthly_x12_fallback"
  else:
    notes["gna_source"] = "other_opex_absolute"

  marketing_annual = _f(fin.get("marketing_total_year1"))
  debt = _f(fin.get("total_debt_outstanding"))
  capex = _f(fin.get("current_capex"))

  # CW-022 #101: the stated-capacity wall on growth (see PRICE_PATH_Q11).
  growth_requested = _f(growth_to_q11, GROWTH_FENCE_Q11)
  wall = capacity_growth_ceiling(ops_json, ann_rev)
  growth_used = min(growth_requested, wall) if wall is not None else growth_requested
  notes["growth"] = {
    "requested": round(growth_requested, 6),
    "capacity_ceiling_multiple": round(wall, 6) if wall is not None else None,
    "used": round(growth_used, 6),
    "capped_by_stated_capacity": bool(wall is not None and growth_used < growth_requested),
  }

  return StructuralBasis(
    q1_revenue_quarterly=ann_rev / 4.0,
    cogs_pct=cogs_pct,
    payroll_quarterly=(payroll + owner_comp_additive) / 4.0,
    rent_quarterly=_f(fin.get("monthly_rent_expense")) * 3.0,
    gna_pct=(gna_annual / ann_rev) if ann_rev else 0.0,
    marketing_pct=(marketing_annual / ann_rev) if ann_rev else 0.0,
    interest_quarterly=debt * SBA_ANNUAL_RATE / 4.0,
    depreciation_quarterly=capex * 0.05,
    growth_to_q11=growth_used,
    notes=notes,
  )


def basis_from_model_input(
  *,
  model_input_json: Dict[str, Any],
  q11_revenue_quarterly: float,
  q11_payroll_quarterly: Optional[float] = None,
  interest_quarterly: float = 0.0,
  depreciation_quarterly: float = 0.0,
) -> Optional[StructuralBasis]:
  """Engine-basis mode (backtest fidelity): the model_input's own Q1
  cost basis (searcher._base_levels) evaluated at a supplied revenue
  point. growth is folded into the supplied revenue (growth_to_q11=1)."""
  from client_intake_and_finmo.post_intake_restructure.searcher import _base_levels

  levels = _base_levels(model_input_json)
  if not levels:
    return None
  payroll_q = (
    q11_payroll_quarterly
    if q11_payroll_quarterly is not None
    else _f(levels.get("annual_payroll")) / 4.0
  )
  return StructuralBasis(
    q1_revenue_quarterly=q11_revenue_quarterly,
    cogs_pct=_f(levels.get("cogs_pct")),
    payroll_quarterly=payroll_q,
    rent_quarterly=_f(levels.get("quarterly_rent")),
    gna_pct=_f(levels.get("g_and_a_pct")),
    marketing_pct=_f(levels.get("marketing_pct")),
    interest_quarterly=interest_quarterly,
    depreciation_quarterly=depreciation_quarterly,
    growth_to_q11=1.0,
    notes={"basis": "model_input_base_levels"},
  )


# ------------------------------------------------------------------ corner

def favorable_corner_basis(
  base: StructuralBasis,
  bounds: Dict[str, Any],
  *,
  existing_line_revenue_split: Optional[List[Dict[str, Any]]] = None,
  payroll_burden_factor: float = 1.0,
) -> StructuralBasis:
  """The joint solver's NI-favorable seed as a closed-form basis:
  prices at market ceilings (volumes held), new lines at market caps,
  costs at their floors (joint_solver.py:313-347 semantics).

  BASIS DISCIPLINE: team bounds are authored in stated-wage terms and
  scaled into the loaded-cost row basis by payroll_burden_factor —
  exactly searcher._dimensions' scaling. Feeding annual where quarterly
  belongs (or unloaded where loaded belongs) is the class of error this
  helper exists to prevent: pass the solver's own bounds, get a basis
  on the solver's own scale.

  `existing_line_revenue_split`: optional [{"q1_revenue_quarterly",
  "price_multiplier_max", "gross_margin_pct"}] per line. When absent,
  the aggregate price ceiling is the revenue-weighted default of 1.0
  (no price move) — conservative.
  """
  rev_existing = base.q1_revenue_quarterly

  # The TRUE most favorable point: prices at their ceilings AND volume
  # at its believable max (price is pure margin; volume carries COGS).
  # A corner-FAIL verdict routes a client to the roadmap — it must not
  # be declarable while any believable lever combination could rescue.
  new_rev_existing = 0.0
  vol_scaled_rev = 0.0  # revenue at old prices, volume maxed — the COGS base
  if existing_line_revenue_split:
    for line in existing_line_revenue_split:
      line_rev = _f(line.get("q1_revenue_quarterly"))
      pmax = max(1.0, _f(line.get("price_multiplier_max"), 1.0))
      vmax = max(1.0, _f(line.get("volume_multiplier_max"), 1.0))
      new_rev_existing += line_rev * pmax * vmax
      vol_scaled_rev += line_rev * vmax
  else:
    new_rev_existing = rev_existing
    vol_scaled_rev = rev_existing

  # New lines at their market caps (q11 quarterly revenue), at their
  # authored gross margins.
  new_line_rev = 0.0
  new_line_cogs = 0.0
  for nl in (bounds.get("new_line_candidates") or []):
    cap = _f((nl or {}).get("q11_quarterly_revenue_max"))
    gm_raw = (nl or {}).get("gross_margin_pct")
    if gm_raw is None:
      # CW-021 ruling (Nick): NO fabricated margin. The old 0.5 default
      # alone decided walk-vs-roadmap on a marginal real shape and was
      # narrated to the client as fact. An unauthored margin earns the
      # favorable corner NO credit for the line.
      continue
    gm_pct = _f(gm_raw)
    new_line_rev += cap
    new_line_cogs += cap * (1.0 - gm_pct)

  # Cost floors.
  team = bounds.get("team") or {}
  bf = max(1.0, min(2.0, _f(payroll_burden_factor, 1.0)))
  payroll_floor_q = _f(team.get("min_annual_payroll")) * bf / 4.0
  payroll_q = min(base.payroll_quarterly, payroll_floor_q) if payroll_floor_q > 0 else base.payroll_quarterly

  fac = bounds.get("facility") or {}
  rent_floor_q = _f(fac.get("min_quarterly_rent"))
  rent_q = min(base.rent_quarterly, rent_floor_q) if rent_floor_q > 0 else base.rent_quarterly

  floors = bounds.get("cost_floors") or {}
  def _floor_pct(current: float, key: str) -> float:
    fv = _opt(floors.get(key))
    return min(current, fv) if fv is not None else current

  # Aggregate corner: existing revenue grown to Q11 at the fence, new
  # lines already authored as Q11 caps (no extra growth on them).
  q11_existing = new_rev_existing * base.growth_to_q11
  q11_rev_total = q11_existing + new_line_rev
  cogs_pct_existing = _floor_pct(base.cogs_pct, "cogs_percent_of_revenue_min")
  # COGS dollars for existing lines: pct of the volume-scaled revenue
  # at OLD prices (price moves are pure margin; volume carries cost),
  # then blended with new-line COGS.
  q11_cogs = (vol_scaled_rev * base.growth_to_q11) * cogs_pct_existing + new_line_cogs
  blended_cogs_pct = (q11_cogs / q11_rev_total) if q11_rev_total > 0 else base.cogs_pct

  corner = StructuralBasis(
    q1_revenue_quarterly=q11_rev_total,
    cogs_pct=blended_cogs_pct,
    payroll_quarterly=payroll_q,
    rent_quarterly=rent_q,
    gna_pct=_floor_pct(base.gna_pct, "g_and_a_percent_of_revenue_min"),
    marketing_pct=_floor_pct(base.marketing_pct, "marketing_percent_of_revenue_min"),
    interest_quarterly=base.interest_quarterly,
    depreciation_quarterly=base.depreciation_quarterly,
    growth_to_q11=1.0,  # growth already folded in above
    notes={"basis": "favorable_corner", "new_line_rev_quarterly": round(new_line_rev, 2)},
  )
  return corner


def evaluate_intake_coherence(
  *,
  financials_json: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  margin_band: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  """Convenience wrapper: intake basis + judged thresholds -> verdict.
  Returns None when no revenue basis exists yet (nothing to evaluate)."""
  basis = basis_from_intake(
    financials_json=financials_json,
    ops_json=ops_json,
    financials_year1_json=financials_year1_json,
  )
  if basis is None:
    return None
  thresholds = thresholds_from_margin_band(margin_band)
  result = evaluate_structural(basis, thresholds)
  result["basis_notes"] = basis.notes
  result["thresholds"] = {
    "gm_floor": thresholds.gm_floor,
    "burden_max": thresholds.burden_max,
    "band_low": thresholds.band_low,
    "band_high": thresholds.band_high,
    "ni_floor": thresholds.ni_floor,
    "judged": thresholds.judged,
  }
  return result


__all__ = [
  "GROWTH_FENCE_Q11",
  "PRICE_PATH_Q11",
  "ops_implied_and_ceiling",
  "capacity_growth_ceiling",
  "SBA_ANNUAL_RATE",
  "COVERAGE_FLOOR",
  "StructuralBasis",
  "Thresholds",
  "thresholds_from_margin_band",
  "evaluate_structural",
  "basis_from_intake",
  "basis_from_model_input",
  "favorable_corner_basis",
  "evaluate_intake_coherence",
]
