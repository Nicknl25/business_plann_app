"""COHERENCE ON THE FORECAST (Nick 2026-09-12, 20:53 and 21:00).

"The numbers from intake are CURRENT ACTUALS. The stub. Q1 to Q20 is a
FORECAST. Coherence is not trying to produce the final forecast - post-intake
does that. Coherence's job is to send it something coherent: numbers that
make sense and a shape that won't fail once the client has left the room.
The bar isn't precision, it's DIRECTIONAL: does this business have a
plausible path to positive net income by Q11, within believable bounds,
given what the client has told us can and can't move? If yes, hand it over.
If no, that's the one conversation that has to happen now."

This module answers that question on the forecast periods with RAMPED
levers, never on one frozen quarter, and never by editing the client's
actuals:

  the stated path     today's actuals grown along the engine's own judged
                      growth path g(q) (growth_multiple_from_judged to each
                      quarter); overhead, marketing and rent held in DOLLARS
                      (the walk scaled overhead with revenue - a percent -
                      which is the one thing this changes); payroll the
                      stated wages, loaded (CW-695), flat; COGS the stated
                      share of revenue.
  the levers as paths annual price steps (at most STEP_MAX a year, from
                      PRICE_START_Q, never past the believable ceiling in
                      dollars); volume ramping to its believable ceiling by
                      LAND_Q; overhead and marketing held; costs never cut
                      by arithmetic. A signed lease pins rent, a contracted
                      price pins prices, a refused family pins its family,
                      the staffing ceiling caps volume.
  the retained rule   the demand judge's conservative edge as a STEP on any
                      moved-price line (the walk's rule). A proportional
                      reading is computed beside it and stored, not used:
                      revisiting the rule is its own change (Nick).
  the test            net income at or above zero at Q11 and every quarter
                      after, to Q20, on the quarter's own basis.
  the proof           every lever is monotone, so the limit path (every
                      lever at its believable ceiling) decides existence:
                      if it does not reach positive net income by Q11 and
                      hold, no path in these bounds does, and the limit path
                      names how far short and by which quarter it turns.

Nothing here calls a model. Nothing here writes an intake field.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.intake_coherence.evaluator import (
  StructuralBasis,
  Thresholds,
  evaluate_structural,
  growth_multiple_from_judged,
)

QUARTERS = tuple(range(1, 21))
Q_TARGET = 11            # positive net income by here, and held to Q20
PRICE_START_Q = 5        # "price rises 3% a year from Q5"
STEP_MAX = 0.06          # an annual price step no larger than this is ordinary
LAND_Q = 11              # volume ramps to its target by Q11
RETAINED_RULE = "step"   # the walk's rule; "proportional" is stored beside it, not used


def _f(v: Any, default: float = 0.0) -> float:
  try:
    if v is None or v == "":
      return default
    return float(v)
  except (TypeError, ValueError):
    return default


@dataclass
class PathLine:
  key: str
  lob: str
  product: str
  rev_q: float
  price: float
  annual_units: float
  pmax: float
  vmax: float


@dataclass
class PathBox:
  base: StructuralBasis          # today's actuals as a basis (growth 1.0)
  thresholds: Thresholds
  lines: List[PathLine]
  growth: Dict[int, float]       # g(q), q = 1..20
  retained_lo: float
  held: Dict[str, str] = field(default_factory=dict)
  notes: Dict[str, Any] = field(default_factory=dict)

  @property
  def n(self) -> int:
    return len(self.lines)

  @property
  def gna_q(self) -> float:
    return self.base.gna_pct * self.base.q1_revenue_quarterly

  @property
  def mkt_q(self) -> float:
    return self.base.marketing_pct * self.base.q1_revenue_quarterly

  @property
  def rest_q(self) -> float:
    return max(0.0, self.base.q1_revenue_quarterly - sum(l.rev_q for l in self.lines))

  def stated(self) -> List[float]:
    return [0.0] * self.n + [1.0] * self.n

  def limit(self) -> List[float]:
    return [STEP_MAX if l.pmax > 1.0 + 1e-6 else 0.0 for l in self.lines] + [l.vmax for l in self.lines]


# ---------------------------------------------------------------- the box

def growth_path(judged_growth: Optional[Dict[str, Any]], ops_json: Optional[Dict[str, Any]],
                fallback_q11: Optional[float] = None) -> Dict[int, float]:
  """g(q) from the engine's own proposer, quarter by quarter; beyond what it
  authors, held at the last authored multiple. With no judgment, a fence
  path to `fallback_q11` at Q11 (geometric) and flat after."""
  g: Dict[int, float] = {}
  last = 1.0
  for q in QUARTERS:
    m = None
    if q > 1:
      try:
        m = growth_multiple_from_judged(judged_growth, ops_json=ops_json, to_quarter=q)
      except Exception:
        m = None
    if m is None or _f(m) <= 0:
      if fallback_q11 and fallback_q11 > 0 and not judged_growth:
        m = min(fallback_q11, fallback_q11 ** ((min(q, Q_TARGET) - 1) / (Q_TARGET - 1))) if q > 1 else 1.0
      else:
        m = last
    g[q] = float(m)
    last = float(m)
  return g


def build_path_box(*, basis_today: StructuralBasis, thresholds: Thresholds, bounds: Dict[str, Any],
                   split: List[Dict[str, Any]], matched: List[Optional[Dict[str, Any]]],
                   growth: Dict[int, float], client_floors: Optional[Dict[str, Any]] = None,
                   demand: Optional[Dict[str, Any]] = None, staffing_cap: Optional[float] = None,
                   effective_pmax=None, effective_vmax=None) -> PathBox:
  cf = dict(client_floors or {})
  held: Dict[str, str] = {}
  vh = (demand or {}).get("volume_headroom") if isinstance(demand, dict) else None
  total_units = sum(_f(l.get("annual_units")) for l in split)
  head_cap = None
  if isinstance(vh, dict) and _f(vh.get("supported_units_max")) > 0 and total_units > 0:
    head_cap = max(1.0, _f(vh["supported_units_max"]) / total_units)
  lines: List[PathLine] = []
  for line, bl in zip(split, matched):
    util = _f(line.get("utilization_rate"), 1.0) or 1.0
    pmax = _f(effective_pmax(line, bl), 1.0) if effective_pmax else max(1.0, _f((bl or {}).get("price_multiplier_max"), 1.0))
    vmax = _f(effective_vmax(line, bl), 1.0) if effective_vmax else max(1.0, _f((bl or {}).get("volume_multiplier_max"), 1.0))
    vmax = min(vmax, (1.0 / util) if 0 < util < 1.0 else 1.0)
    if head_cap is not None:
      vmax = min(vmax, head_cap)
    if staffing_cap is not None and _f(staffing_cap) >= 1.0:
      vmax = min(vmax, _f(staffing_cap))
    if cf.get("pricing"):
      pmax = 1.0
    if cf.get("volume"):
      vmax = 1.0
    lines.append(PathLine(key=f"{line['lob']}␟{line['product']}", lob=str(line.get("lob") or ""),
                          product=str(line.get("product") or ""), rev_q=_f(line.get("q1_revenue_quarterly")),
                          price=_f(line.get("unit_price")), annual_units=_f(line.get("annual_units")),
                          pmax=max(1.0, pmax), vmax=max(1.0, vmax)))
  if cf.get("pricing"):
    held["pricing"] = "prices held as you asked"
  if cf.get("volume"):
    held["volume"] = "volume held as you asked"
  if cf.get("rent"):
    held["rent"] = "rent held as you asked"
  held["payroll"] = "the team as stated - never cut by arithmetic"
  held["overhead"] = "other operating costs held in dollars while revenue grows - never cut by arithmetic"
  pr = (demand or {}).get("price_response") if isinstance(demand, dict) else None
  retained = 1.0
  if isinstance(pr, dict) and isinstance(pr.get("retained_fraction_band"), (list, tuple)) and pr["retained_fraction_band"]:
    retained = min(1.0, max(0.0, _f(pr["retained_fraction_band"][0], 1.0)))
  return PathBox(base=basis_today, thresholds=thresholds, lines=lines, growth=dict(growth), retained_lo=retained, held=held,
                 notes={"head_cap": head_cap, "staffing_cap": staffing_cap, "retained_rule": RETAINED_RULE})


# ---------------------------------------------------------------- the arithmetic, quarter by quarter

def price_multiplier(box: PathBox, i: int, step: float, q: int) -> float:
  if step <= 1e-9 or q < PRICE_START_Q:
    return 1.0
  years = (q - PRICE_START_Q) // 4 + 1
  return min(box.lines[i].pmax, (1.0 + step) ** years)


def retained_fraction(box: PathBox, i: int, pm: float, rule: str = RETAINED_RULE) -> float:
  if pm <= 1.0 + 1e-9:
    return 1.0
  if rule == "step":
    return box.retained_lo
  span = max(box.lines[i].pmax - 1.0, 1e-9)
  return 1.0 - (1.0 - box.retained_lo) * min(1.0, (pm - 1.0) / span)


def quarter_basis(box: PathBox, x: List[float], q: int, rule: str = RETAINED_RULE) -> StructuralBasis:
  """The quarter's own basis under the path x = [steps..., volume targets...]:
  revenue grows along g(q), volume ramps to its target by LAND_Q, prices step
  annually from PRICE_START_Q; overhead, marketing and rent hold in dollars;
  payroll holds; COGS rides the volume-scaled revenue at old prices."""
  n = box.n
  steps, vt = x[:n], x[n:2 * n]
  g = box.growth.get(q, 1.0)
  rev = box.rest_q * g
  vol_rev = box.rest_q * g
  for i, l in enumerate(box.lines):
    v = 1.0 + (vt[i] - 1.0) * min(1.0, (q - 1) / float(LAND_Q - 1))
    pm = price_multiplier(box, i, steps[i], q)
    ret = retained_fraction(box, i, pm, rule)
    rev += l.rev_q * g * v * pm * ret
    vol_rev += l.rev_q * g * v * ret
  if rev <= 0:
    return box.base
  return StructuralBasis(
    q1_revenue_quarterly=rev,
    cogs_pct=box.base.cogs_pct * vol_rev / rev,
    payroll_quarterly=box.base.payroll_quarterly,
    rent_quarterly=box.base.rent_quarterly,
    gna_pct=box.gna_q / rev,
    marketing_pct=box.mkt_q / rev,
    interest_quarterly=box.base.interest_quarterly,
    depreciation_quarterly=box.base.depreciation_quarterly,
    growth_to_q11=1.0,
    notes={"basis": "forecast_quarter", "q": q},
  )


def evaluate_path(box: PathBox, x: List[float], rule: str = RETAINED_RULE) -> Dict[str, Any]:
  """Every quarter's own numbers, the first quarter net income turns positive,
  and whether it is positive at Q11 and every quarter after."""
  quarters: Dict[int, Dict[str, Any]] = {}
  for q in QUARTERS:
    r = evaluate_structural(quarter_basis(box, x, q, rule), box.thresholds)
    q11 = r.get("q11") or {}
    quarters[q] = {
      "revenue": round(_f(q11.get("revenue")), 2), "ebitda": round(_f(q11.get("ebitda")), 2),
      "ebitda_margin": round(_f(q11.get("ebitda_margin")), 4), "ni_margin": round(_f(q11.get("ni_margin")), 4),
      "ni": round(_f(q11.get("ebitda")) - box.base.interest_quarterly - box.base.depreciation_quarterly, 2),
      "burden": round((_f(q11.get("payroll")) + _f(q11.get("rent")) + _f(q11.get("gna"))) / max(_f(q11.get("revenue")), 1e-9), 4),
      "tests_passed": bool(r.get("passed")), "gap_quarterly": round(_f(r.get("gap_quarterly")), 2),
    }
  first_positive = next((q for q in QUARTERS if quarters[q]["ni"] >= 0.0), None)
  holds = all(quarters[q]["ni"] >= 0.0 for q in range(Q_TARGET, 21))
  worst_short = max(0.0, max(-quarters[q]["ni"] for q in range(Q_TARGET, 21)))
  first_full_pass = next((q for q in QUARTERS if quarters[q]["tests_passed"]), None)
  return {"quarters": quarters, "first_positive_ni_q": first_positive, "positive_by_target_and_holds": holds,
          "worst_ni_short_from_target": round(worst_short, 2), "first_full_pass_q": first_full_pass,
          "points": {q: quarters[q] for q in (1, 5, Q_TARGET, 20)}}


# ---------------------------------------------------------------- feasibility: stated, limit, proof

def describe_levers(box: PathBox, x: List[float]) -> List[str]:
  out: List[str] = []
  n = box.n
  for i, l in enumerate(box.lines):
    if x[i] > 1e-4:
      out.append(f"{l.product} price rising about {x[i]:.0%} a year from Q{PRICE_START_Q}, never past ${l.price * l.pmax:,.2f}")
    if x[n + i] > 1.0 + 1e-4:
      out.append(f"{l.product} volume growing to {x[n + i] - 1.0:+.0%} by Q{LAND_Q}")
  return out


def feasibility(box: PathBox) -> Dict[str, Any]:
  """The directional answer. coherent_as_stated: the stated path alone turns
  positive by Q11 and holds. feasible: the limit path does (every lever at
  its believable ceiling) - the proof when it does not."""
  stated = evaluate_path(box, box.stated())
  limit = evaluate_path(box, box.limit())
  out: Dict[str, Any] = {
    "target_q": Q_TARGET,
    "coherent_as_stated": bool(stated["positive_by_target_and_holds"]),
    "feasible": bool(limit["positive_by_target_and_holds"]),
    "stated": {k: stated[k] for k in ("first_positive_ni_q", "positive_by_target_and_holds", "worst_ni_short_from_target", "first_full_pass_q", "points")},
    "limit": {k: limit[k] for k in ("first_positive_ni_q", "positive_by_target_and_holds", "worst_ni_short_from_target", "first_full_pass_q", "points")},
    "levers_at_limit": describe_levers(box, box.limit()),
    "held": dict(box.held),
    "retained_rule": RETAINED_RULE, "retained_edge": box.retained_lo,
    "ceilings": [{"product": l.product, "price_max": round(l.pmax, 4), "volume_max": round(l.vmax, 4)} for l in box.lines],
  }
  if RETAINED_RULE == "step" and box.retained_lo < 1.0:
    alt = evaluate_path(box, box.limit(), rule="proportional")
    out["proportional_reading"] = {k: alt[k] for k in ("first_positive_ni_q", "positive_by_target_and_holds", "worst_ni_short_from_target")}
  return out


def proof_sentence(feas: Dict[str, Any]) -> str:
  """'Every lever at its believable limit still leaves ...' - what the roadmap should always have said."""
  lim = feas.get("limit") or {}
  pts = lim.get("points") or {}
  q11 = pts.get(Q_TARGET) or {}
  q20 = pts.get(20) or {}
  turn = lim.get("first_positive_ni_q")
  when = f"and turns positive only at Q{turn}" if turn else "and never turns positive in the five years"
  levers = feas.get("levers_at_limit") or []
  lv = ("; ".join(levers)) if levers else "no lever is free to move"
  return (
    f"Every lever at its believable limit ({lv}) still leaves net income at {_f(q11.get('ni_margin')):+.0%} of revenue at Q{Q_TARGET} "
    f"({_f(q20.get('ni_margin')):+.0%} at Q20) {when}."
  )


# ---------------------------------------------------------------- the three configurations
# (Nick 21:03: one round, three complete configurations, the client picks one -
# that is the agreement; the executive refines within it)

SHAPE_LEAST_CHANGE = "least_change"
SHAPE_REVENUE_LED = "revenue_led"
SHAPE_COST_LED = "cost_led"
SHAPES = (SHAPE_LEAST_CHANGE, SHAPE_REVENUE_LED, SHAPE_COST_LED)
CONFIG_ID = {SHAPE_LEAST_CHANGE: "config_least_change", SHAPE_REVENUE_LED: "config_revenue_led", SHAPE_COST_LED: "config_cost_led"}
SHAPE_LABEL = {SHAPE_LEAST_CHANGE: "Least change from what you told me",
               SHAPE_REVENUE_LED: "Revenue-led: prices and volume do the work, costs as they are",
               SHAPE_COST_LED: "Cost-led: the cost lines do the work, prices and volume barely move"}
# x = [price steps (n), volume targets (n), cogs share target, overhead dollars target]; the two targets glide to target by LAND_Q
_W = {SHAPE_LEAST_CHANGE: (1.0, 1.0), SHAPE_REVENUE_LED: (1.0, 60.0), SHAPE_COST_LED: (60.0, 1.0)}


def _cost_floors(box: PathBox, bounds: Dict[str, Any], client_floors: Optional[Dict[str, Any]]) -> Dict[str, float]:
  cf = dict(client_floors or {})
  floors = (bounds or {}).get("cost_floors") or {}
  cogs_floor = box.base.cogs_pct if cf.get("cogs") else min(box.base.cogs_pct, _f(floors.get("cogs_percent_of_revenue_min"), box.base.cogs_pct) or box.base.cogs_pct)
  gna_floor = box.gna_q if cf.get("gna") else min(box.gna_q, (_f(floors.get("g_and_a_percent_of_revenue_min"), box.base.gna_pct) or box.base.gna_pct) * box.base.q1_revenue_quarterly)
  return {"cogs_floor": cogs_floor, "gna_floor_q": gna_floor}


def quarter_basis_cfg(box: PathBox, x: List[float], q: int, rule: str = RETAINED_RULE) -> StructuralBasis:
  """quarter_basis with the two cost targets gliding from stated to target by LAND_Q."""
  n = box.n
  b = quarter_basis(box, list(x[:2 * n]), q, rule)
  if len(x) < 2 * n + 2:
    return b
  t = min(1.0, (q - 1) / float(LAND_Q - 1))
  cogs_t = box.base.cogs_pct + (x[2 * n] - box.base.cogs_pct) * t
  gna_t = box.gna_q + (x[2 * n + 1] - box.gna_q) * t
  rev = b.q1_revenue_quarterly
  return StructuralBasis(q1_revenue_quarterly=rev,
                         cogs_pct=b.cogs_pct * (cogs_t / box.base.cogs_pct if box.base.cogs_pct > 0 else 1.0),
                         payroll_quarterly=b.payroll_quarterly, rent_quarterly=b.rent_quarterly, gna_pct=gna_t / rev,
                         marketing_pct=b.marketing_pct, interest_quarterly=b.interest_quarterly,
                         depreciation_quarterly=b.depreciation_quarterly, growth_to_q11=1.0, notes={"basis": "forecast_quarter", "q": q})


def evaluate_cfg(box: PathBox, x: List[float], rule: str = RETAINED_RULE) -> Dict[str, Any]:
  quarters: Dict[int, Dict[str, Any]] = {}
  for q in QUARTERS:
    r = evaluate_structural(quarter_basis_cfg(box, x, q, rule), box.thresholds)
    q11 = r.get("q11") or {}
    quarters[q] = {"revenue": round(_f(q11.get("revenue")), 2), "ebitda": round(_f(q11.get("ebitda")), 2),
                   "ebitda_margin": round(_f(q11.get("ebitda_margin")), 4), "ni_margin": round(_f(q11.get("ni_margin")), 4),
                   "ni": round(_f(q11.get("ebitda")) - box.base.interest_quarterly - box.base.depreciation_quarterly, 2),
                   "burden": round((_f(q11.get("payroll")) + _f(q11.get("rent")) + _f(q11.get("gna"))) / max(_f(q11.get("revenue")), 1e-9), 4),
                   "tests_passed": bool(r.get("passed"))}
  holds = all(quarters[q]["ni"] >= 0.0 for q in range(Q_TARGET, 21))
  return {"quarters": quarters, "first_positive_ni_q": next((q for q in QUARTERS if quarters[q]["ni"] >= 0.0), None),
          "positive_by_target_and_holds": holds,
          "worst_ni_short_from_target": round(max(0.0, max(-quarters[q]["ni"] for q in range(Q_TARGET, 21))), 2),
          "first_full_pass_q": next((q for q in QUARTERS if quarters[q]["tests_passed"]), None),
          "points": {q: quarters[q] for q in (1, 5, Q_TARGET, 20)}}


def _movement(box: PathBox, x: List[float], w: Tuple[float, float]) -> float:
  n = box.n
  total = sum(l.rev_q for l in box.lines) or 1.0
  rev_side = sum((l.rev_q / total) * (x[i] * 10.0 + (x[n + i] - 1.0)) for i, l in enumerate(box.lines))
  cost_side = 0.0
  if len(x) >= 2 * n + 2:
    cost_side = ((box.base.cogs_pct - x[2 * n]) / box.base.cogs_pct if box.base.cogs_pct > 0 else 0.0)
    cost_side += ((box.gna_q - x[2 * n + 1]) / box.gna_q if box.gna_q > 0 else 0.0)
  return w[0] * rev_side + w[1] * cost_side


def solve_configurations(box: PathBox, bounds: Dict[str, Any], client_floors: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
  """The proof and up to three complete configurations on the forecast:
  price steps, volume ramps, and (cost-led) the cost lines gliding to their
  judged floors by Q11. Feasible = net income at or above zero at Q11 and
  every quarter after. Deterministic (seed 7)."""
  from scipy.optimize import minimize
  n = box.n
  fl = _cost_floors(box, bounds, client_floors)
  lo = [0.0] * n + [1.0] * n + [fl["cogs_floor"], fl["gna_floor_q"]]
  hi = [STEP_MAX if l.pmax > 1.0 + 1e-6 else 0.0 for l in box.lines] + [l.vmax for l in box.lines] + [box.base.cogs_pct, box.gna_q]
  hi = [max(h, l_ + 1e-9) for h, l_ in zip(hi, lo)]
  stated = [0.0] * n + [1.0] * n + [box.base.cogs_pct, box.gna_q]
  # THE LIMIT IS THE BEST CORNER, NOT THE BIGGEST: under the walk's retained
  # rule a price rise loses customers, so a line's price step is NOT
  # monotone - the limit is taken over every on/off pattern of price moves
  # (at most 2^n, n the lines), volume and the cost lines at their limits.
  import itertools as _it
  movable = [i for i, l in enumerate(box.lines) if l.pmax > 1.0 + 1e-6]
  best_pat, best_short, limit = None, None, None
  for k in range(len(movable) + 1):
    for pat in _it.combinations(movable, k):
      cand = [(hi[i] if i in pat else 0.0) for i in range(n)] + hi[n:2 * n] + lo[2 * n:]
      sh = evaluate_cfg(box, cand)["worst_ni_short_from_target"]
      if best_short is None or sh < best_short - 1e-9:
        best_pat, best_short, limit = set(pat), sh, cand
  hi = [(hi[i] if i in (best_pat or set()) else 0.0) for i in range(n)] + hi[n:]
  ev_stated = evaluate_cfg(box, stated)
  ev_limit = evaluate_cfg(box, limit)
  keys = ("first_positive_ni_q", "positive_by_target_and_holds", "worst_ni_short_from_target", "first_full_pass_q", "points")
  levers = describe_levers(box, limit)
  if fl["cogs_floor"] < box.base.cogs_pct - 1e-4:
    levers.append(f"direct costs easing to {fl['cogs_floor']:.0%} of revenue by Q{LAND_Q}")
  if fl["gna_floor_q"] < box.gna_q - 1:
    levers.append(f"other operating costs easing to ${fl['gna_floor_q'] * 4:,.0f} a year by Q{LAND_Q}")
  out: Dict[str, Any] = {
    "target_q": Q_TARGET,
    "coherent_as_stated": bool(ev_stated["positive_by_target_and_holds"]),
    "feasible": bool(ev_limit["positive_by_target_and_holds"]),
    "stated": {k: ev_stated[k] for k in keys},
    "limit": {k: ev_limit[k] for k in keys},
    "levers_at_limit": levers,
    "held": dict(box.held), "retained_rule": RETAINED_RULE, "retained_edge": box.retained_lo,
    "ceilings": [{"product": l.product, "price_max": round(l.pmax, 4), "volume_max": round(l.vmax, 4)} for l in box.lines],
    "configurations": [],
  }
  if RETAINED_RULE == "step" and box.retained_lo < 1.0:
    alt = evaluate_cfg(box, limit, rule="proportional")
    out["proportional_reading"] = {k: alt[k] for k in ("first_positive_ni_q", "positive_by_target_and_holds", "worst_ni_short_from_target")}
  if out["coherent_as_stated"] or not out["feasible"]:
    return out

  def short(x):
    return evaluate_cfg(box, list(x))["worst_ni_short_from_target"]
  gap0 = max(short(stated), 1.0)
  seen: List[List[float]] = []
  for shape in SHAPES:
    w = _W[shape]
    # least change holds overhead flat in dollars (Nick: "overhead holds flat
    # while revenue grows, nobody loses a job") and eases it toward the judged
    # floor only when holding it cannot close; revenue-led pins every cost
    # line; cost-led puts the cost lines at their floors first.
    variants = [("overhead_held",), ("overhead_free",)] if shape == SHAPE_LEAST_CHANGE else [(None,)]
    picked = None
    for (variant,) in variants:
      b_lo, b_hi = list(lo), list(hi)
      if shape == SHAPE_REVENUE_LED:
        b_lo[2 * n:] = [box.base.cogs_pct, box.gna_q]
        b_hi[2 * n:] = [box.base.cogs_pct + 1e-9, box.gna_q + 1e-9]
      if variant == "overhead_held":
        b_lo[2 * n + 1], b_hi[2 * n + 1] = box.gna_q, box.gna_q + 1e-9
      shape_limit = b_hi[:2 * n] + b_lo[2 * n:]
      if short(shape_limit) <= 0.0:
        picked = (b_lo, b_hi, shape_limit)
        break
    if picked is None:
      continue   # this shape cannot close on its own - it is not offered
    b_lo, b_hi, shape_limit = picked
    seg_lo = [min(max(v, l_), h) for v, l_, h in zip(stated, b_lo, b_hi)]
    if shape == SHAPE_COST_LED:
      # the cost lines go to their floors first; prices and volume only as far as the costs cannot carry
      seg_lo = seg_lo[:2 * n] + list(shape_limit[2 * n:])
      if short(seg_lo) <= 0.0:
        x = list(seg_lo)
      else:
        x = None
    else:
      x = None
    if x is None:
      # THE SEGMENT: every lever only helps, so the least t with the target
      # held is a bisection (22 steps), then a short polish inside the
      # shape's box weighted for its objective.
      def at(t, a=seg_lo, b=shape_limit):
        return [u + (v - u) * t for u, v in zip(a, b)]
      t_lo, t_hi = 0.0, 1.0
      for _ in range(22):
        mid = 0.5 * (t_lo + t_hi)
        if short(at(mid)) <= 0.0:
          t_hi = mid
        else:
          t_lo = mid
      # two percent inside the segment: a configuration sits inside
      # feasibility, never on its edge (a six-decimal rounding must not tip
      # Q11 a few cents negative)
      x = at(min(1.0, t_hi + 0.02))
    try:
      res2 = minimize(lambda y: _movement(box, list(y), w) + 500.0 * max(0.0, short(y)) / gap0, x,
                      bounds=list(zip(b_lo, b_hi)), method="Powell", options={"maxfev": 400, "xtol": 1e-3, "ftol": 1e-4})
      xp = [float(min(max(v, l_), h)) for v, l_, h in zip(res2.x, b_lo, b_hi)]
      if short(xp) <= 0.0 and _movement(box, xp, w) < _movement(box, x, w) - 1e-9:
        x = xp
    except Exception:
      pass
    x = [round(v, 6) for v in x]
    if short(x) > 0.0:
      continue
    if any(max(abs(a - b) for a, b in zip(x, y)) < 1e-3 for y in seen):
      continue
    seen.append(x)
    ev = evaluate_cfg(box, x)
    moves = describe_levers(box, x)
    if x[2 * n] < box.base.cogs_pct - 1e-4:
      moves.append(f"direct costs easing from {box.base.cogs_pct:.1%} to {x[2 * n]:.1%} of revenue by Q{LAND_Q}")
    if x[2 * n + 1] < box.gna_q - 1:
      moves.append(f"other operating costs easing from ${box.gna_q * 4:,.0f} to ${x[2 * n + 1] * 4:,.0f} a year by Q{LAND_Q}")
    else:
      moves.append("other operating costs held flat in dollars while revenue grows")
    p11 = ev["points"][Q_TARGET]
    p20 = ev["points"][20]
    why = ("; ".join(moves) + f". Net income turns positive at Q{ev['first_positive_ni_q']}; at Q{Q_TARGET} the business brings in "
           f"${p11['revenue']:,.0f} a quarter and keeps {p11['ni_margin']:+.0%} after interest and depreciation, at Q20 {p20['ni_margin']:+.0%}.")
    out["configurations"].append({
      "id": CONFIG_ID[shape], "shape": shape, "label": SHAPE_LABEL[shape], "x": [round(v, 6) for v in x],
      "moves": moves, "why": why, "points": ev["points"], "first_positive_ni_q": ev["first_positive_ni_q"],
      "first_full_pass_q": ev["first_full_pass_q"], "movement": round(_movement(box, x, (1.0, 1.0)), 6),
      "directive": directive_for(box, x),
    })
  if out["configurations"]:
    out["configurations"][0]["recommended"] = True
  return out


def directive_for(box: PathBox, x: List[float]) -> Dict[str, Any]:
  """The chosen configuration in the restructure stage's directive format
  (the initial-grid runner consumes it): per-line price multipliers AT Q11
  and Q20 under the annual steps, the volume targets, the cost shares at
  Q11, rent as stated, the team as stated. The executive refines within it."""
  n = box.n
  lines_out = []
  for i, l in enumerate(box.lines):
    p11 = price_multiplier(box, i, x[i], Q_TARGET)
    p20 = price_multiplier(box, i, x[i], 20)
    v = x[n + i]
    if p11 > 1.0 + 1e-6 or p20 > 1.0 + 1e-6 or v > 1.0 + 1e-6:
      lines_out.append({"lob": l.lob, "product": l.product,
                        "volume_multiplier_q11": round(v, 6), "volume_multiplier_q20": round(v, 6),
                        "price_multiplier_q11": round(p11, 6), "price_multiplier_q20": round(p20, 6),
                        "price_step_annual": round(x[i], 6), "price_start_q": PRICE_START_Q,
                        "rationale": "the configuration the client chose at intake: annual price steps within the believable ceiling, volume ramping by Q11"})
  b11 = quarter_basis_cfg(box, x, Q_TARGET)
  pb = (box.base.notes or {}).get("payroll_basis") or {}
  stated_wages = _f(pb.get("stated_wages_annual")) or (box.base.payroll_quarterly * 4.0)
  return {
    "feasible": True, "source": "intake_coherence_path",
    "team": {"annual_payroll": round(stated_wages, 2), "structure": "", "rationale": "the team as stated - never cut by arithmetic"},
    "pricing": {"price_multiplier_q11": 1.0, "price_multiplier_q20": 1.0, "rationale": "per-line pricing rides revenue_mix.lines"},
    "facility": {"quarterly_rent_target": round(box.base.rent_quarterly, 2), "rationale": "rent as stated"},
    "growth": {},
    "revenue_mix": {"lines": lines_out, "new_lines": []},
    "cost_structure": {"cogs_percent_of_revenue": round(b11.cogs_pct, 6), "marketing_percent_of_revenue": round(b11.marketing_pct, 6),
                       "g_and_a_percent_of_revenue": round(b11.gna_pct, 6),
                       "rationale": "the shares at Q11 under the chosen configuration: overhead held in dollars while revenue grows"},
    "product_mix_notes": "",
    "overall_rationale": "the configuration the client chose at intake; the executive shapes the path within it",
    "reality_constraints": {}, "notes": ["intake_coherence_path"],
  }


__all__ = [
  "QUARTERS", "Q_TARGET", "PRICE_START_Q", "STEP_MAX", "LAND_Q", "RETAINED_RULE",
  "PathBox", "PathLine", "growth_path", "build_path_box", "quarter_basis", "evaluate_path",
  "feasibility", "describe_levers", "proof_sentence",
  "SHAPES", "CONFIG_ID", "SHAPE_LABEL", "solve_configurations", "evaluate_cfg", "quarter_basis_cfg", "directive_for",
]
