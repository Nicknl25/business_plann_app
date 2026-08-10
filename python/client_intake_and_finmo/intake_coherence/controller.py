"""COHERENCE LOOP CONTROLLER — deterministic Python drives; GPT phrases.

The controller owns everything numeric about the coherence section:
evaluation, corner-first, round selection (one binding constraint at a
time, largest dollar-gap-closure first), option generation (every
option inside the executive's judged bounds, every option carrying the
concrete intake-field patch it maps to), gap movement acknowledgment,
and the three honest exits (converged / parked / roadmap).

It never writes to the draft and never talks to GPT — intake_consult
wires persistence (repair_guidance_json["coherence"]) and phrasing
around it. Numbers in the phrasing payloads are preformatted here so
the phrasing layer can NEVER invent a figure.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.intake_coherence.evaluator import (
  StructuralBasis,
  Thresholds,
  basis_from_intake,
  evaluate_structural,
  favorable_corner_basis,
  thresholds_from_margin_band,
)

# Statuses of the coherence section (persisted in
# repair_guidance_json["coherence"]["status"]):
#   pending    — not yet evaluated (financials still accumulating)
#   walking    — structural FAIL, corner passes, lever walk in progress
#   converged  — checks pass on the stated configuration
#   parked     — client explicitly deferred; draft stays open
#   roadmap    — corner fails; roadmap conversation / no plan ships
STATUS_PENDING = "pending"
STATUS_WALKING = "walking"
STATUS_CONVERGED = "converged"
STATUS_PARKED = "parked"
STATUS_ROADMAP = "roadmap"

# Round keys, in narrative order. Selection is by dollar closure, but
# ties/near-ties fall back to this order (price before cost trims —
# revenue-side moves are the client's own market story).
ROUND_PRICING = "pricing"
ROUND_NEW_LINES = "new_lines"
ROUND_COSTS = "cost_structure"
ROUND_VOLUME = "volume"


def _fmt_money(v: float) -> str:
  return ("-$" if v < 0 else "$") + f"{abs(v):,.0f}"


def _f(value: Any, default: float = 0.0) -> float:
  try:
    if value in (None, ""):
      return default
    n = float(value)
  except (TypeError, ValueError):
    return default
  return default if n != n else n


def stable_digest_hash(compact: Optional[Dict[str, Any]]) -> str:
  """Identity hash of the compact digest — the ONLY invalidation key
  for the margin-band stamp (identity-level change re-judges; knob
  changes never do)."""
  try:
    canonical = json.dumps(compact or {}, sort_keys=True, separators=(",", ":"))
  except (TypeError, ValueError):
    canonical = "{}"
  return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ops_line_split(
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  """Per-line Q1 quarterly revenue from the ops model's own drivers
  (lob_models[].products[]), scaled to the stated revenue anchor the
  engine itself uses. Empty when the shape isn't derivable."""
  lines: List[Dict[str, Any]] = []
  ops = ops_json if isinstance(ops_json, dict) else {}
  for lob in ops.get("lob_models") or []:
    if not isinstance(lob, dict):
      continue
    # live ops shape: lob_models[].lob_name / products[].product_name
    # (the digest builder's own keys) with legacy fallbacks
    lob_name = str(lob.get("lob_name") or lob.get("lob") or lob.get("name") or "").strip()
    for p in lob.get("products") or []:
      if not isinstance(p, dict):
        continue
      price = _f(p.get("unit_price"))
      cap = _f(p.get("units_per_period_capacity")) or _f(p.get("units_per_week_capacity"))
      util = _f(p.get("utilization_rate"), 1.0)
      periods = _f(p.get("operating_periods_per_year"), 12.0)
      if price > 0 and cap > 0:
        lines.append({
          "lob": lob_name,
          "product": str(p.get("product_name") or p.get("product") or p.get("name") or "").strip(),
          "unit_price": price,
          "annual_revenue": price * cap * util * periods,
          # volume-lever drivers (phase 4): the round needs the physical
          # knobs to land a believable volume move on the ops truth.
          "units_per_period_capacity": cap,
          "utilization_rate": util,
          "operating_periods_per_year": periods,
          "annual_units": cap * util * periods,
        })
  total = sum(l["annual_revenue"] for l in lines)
  if total <= 0:
    return []
  ann_rev = _f((financials_json or {}).get("current_revenue")) or total
  scale = ann_rev / total
  for l in lines:
    l["q1_revenue_quarterly"] = round(l["annual_revenue"] * scale / 4.0, 2)
  return lines


def match_bounds_lines(
  split: List[Dict[str, Any]],
  bounds: Dict[str, Any],
) -> List[Optional[Dict[str, Any]]]:
  """Match each split line to its authored bounds line: exact
  (lob, product) name match first, then product-only, then — when the
  counts align — by position (the executive authors lines in the order
  it saw them; the walk E2E proved name drift between the intake ops
  shape and the GPT's own labels makes pure name matching false-drop
  every lever, which silently weakens the corner)."""
  blines = [b for b in (bounds.get("existing_lines") or []) if isinstance(b, dict)]

  def _norm(s: Any) -> str:
    return " ".join(str(s or "").lower().split())

  out: List[Optional[Dict[str, Any]]] = []
  used = set()
  for line in split:
    match = None
    for i, b in enumerate(blines):
      if i in used:
        continue
      if (_norm(b.get("lob")), _norm(b.get("product"))) == (_norm(line.get("lob")), _norm(line.get("product"))):
        match = (i, b)
        break
    if match is None:
      for i, b in enumerate(blines):
        if i in used:
          continue
        pn = _norm(b.get("product"))
        ln = _norm(line.get("product"))
        if pn and ln and (pn in ln or ln in pn):
          match = (i, b)
          break
    if match is not None:
      used.add(match[0])
      out.append(match[1])
    else:
      out.append(None)
  if any(m is None for m in out) and len(split) == len(blines):
    # positional fallback: counts align — zip in order
    out = list(blines)
  return out


def _effective_pmax(line: Dict[str, Any], bl: Optional[Dict[str, Any]]) -> float:
  """CW-022 #3 (Nick-ruled, intake-pure): the judged price ceiling holds
  in DOLLARS. The author judges "the highest price this line's real
  customers demonstrably pay" against the price it was shown, but the
  schema stores a RATIO — re-based on the live price, every client price
  move silently inflated the "believable" ceiling (Fetch & Fluff: judged
  $108 became a $144 offer after the client moved to $80 — the ratchet).
  With the authoring-time price stamped at storage, the effective
  multiplier is capped so current x m never exceeds authoring x pmax.
  Un-stamped legacy bounds keep the old relative behavior."""
  pmax = max(1.0, _f((bl or {}).get("price_multiplier_max"), 1.0))
  p0 = _f((bl or {}).get("unit_price_at_authoring"))
  cur = _f(line.get("unit_price"))
  if p0 > 0 and cur > 0:
    return max(1.0, min(pmax, (p0 * pmax) / cur))
  return pmax


def _effective_vmax(line: Dict[str, Any], bl: Optional[Dict[str, Any]]) -> float:
  """Volume analog of the price-ratchet fix (CW-022 #3 pattern): the
  judged volume ceiling holds in UNITS. volume_multiplier_max is stored
  as a RATIO - re-based on the live volume, every accepted volume move
  would inflate the believable ceiling. With the authoring-time annual
  units stamped, current x m never exceeds authoring x vmax. Un-stamped
  legacy bounds keep the relative behavior."""
  vmax = max(1.0, _f((bl or {}).get("volume_multiplier_max"), 1.0))
  u0 = _f((bl or {}).get("annual_units_at_authoring"))
  cur = _f(line.get("annual_units"))
  if u0 > 0 and cur > 0:
    return max(1.0, min(vmax, (u0 * vmax) / cur))
  return vmax


def _volume_move_basis(
  basis: StructuralBasis,
  split: List[Dict[str, Any]],
  multipliers: Dict[str, float],
) -> StructuralBasis:
  """Basis with per-line VOLUME multipliers applied. Corner semantics
  (favorable_corner_basis): volume carries COGS - the cogs percent
  HOLDS (more units cost proportionally more to deliver); dollar
  overheads (G&A, marketing) hold, so their pcts rescale; payroll and
  rent hold (the bounds author judged the ceiling reachable with the
  current setup)."""
  base_rev = basis.q1_revenue_quarterly
  new_rev = 0.0
  covered = 0.0
  for line in split:
    key = f"{line['lob']}␟{line['product']}"
    m = max(1.0, _f(multipliers.get(key), 1.0))
    new_rev += line["q1_revenue_quarterly"] * m
    covered += line["q1_revenue_quarterly"]
  new_rev += max(0.0, base_rev - covered)
  if new_rev <= 0:
    return basis
  ratio = base_rev / new_rev
  return StructuralBasis(
    q1_revenue_quarterly=new_rev,
    cogs_pct=basis.cogs_pct,  # volume carries COGS
    payroll_quarterly=basis.payroll_quarterly,
    rent_quarterly=basis.rent_quarterly,
    gna_pct=basis.gna_pct * ratio,
    marketing_pct=basis.marketing_pct * ratio,
    interest_quarterly=basis.interest_quarterly,
    depreciation_quarterly=basis.depreciation_quarterly,
    growth_to_q11=basis.growth_to_q11,
    notes=dict(basis.notes),
  )


def _volume_landing(line: Dict[str, Any], m: float) -> Dict[str, Any]:
  """Land a volume multiplier on the ops truth, utilization-first: fill
  the book that already exists (util up to 100%), and only the
  remainder widens capacity - so the physical ceiling stays honest
  (the anchor-vs-ops check prices capacity at 100%)."""
  util = max(1e-9, min(1.0, _f(line.get("utilization_rate"), 1.0)))
  cap = _f(line.get("units_per_period_capacity"))
  new_util = min(1.0, util * m)
  cap_mult = (m * util) / new_util if new_util > 0 else 1.0
  return {
    "lob": line["lob"], "product": line["product"],
    "utilization_rate": round(new_util, 4),
    "units_per_period_capacity": round(cap * cap_mult, 4),
  }


def _price_move_basis(
  basis: StructuralBasis,
  split: List[Dict[str, Any]],
  multipliers: Dict[str, float],
) -> StructuralBasis:
  """Basis with per-line price multipliers applied: revenue scales, and
  ALL dollar-denominated costs hold (volume held — price is pure
  margin). CW-022 #7: G&A and marketing derive from FIXED dollar fields
  in basis_from_intake, so holding only COGS dollars while G&A/marketing
  scaled with revenue made this projection disagree with the re-eval the
  panel gap runs — the closes-$0 lie (a price rise projected as
  WORSENING the gap on a fixed-cost-heavy shape)."""
  base_rev = basis.q1_revenue_quarterly
  new_rev = 0.0
  covered = 0.0
  for line in split:
    key = f"{line['lob']}␟{line['product']}"
    m = max(1.0, _f(multipliers.get(key), 1.0))
    new_rev += line["q1_revenue_quarterly"] * m
    covered += line["q1_revenue_quarterly"]
  new_rev += max(0.0, base_rev - covered)  # any un-split remainder unmoved
  if new_rev <= 0:
    return basis
  # Dollar costs held: pcts rescale by the revenue ratio.
  ratio = base_rev / new_rev
  return StructuralBasis(
    q1_revenue_quarterly=new_rev,
    cogs_pct=basis.cogs_pct * ratio,
    payroll_quarterly=basis.payroll_quarterly,
    rent_quarterly=basis.rent_quarterly,
    gna_pct=basis.gna_pct * ratio,
    marketing_pct=basis.marketing_pct * ratio,
    interest_quarterly=basis.interest_quarterly,
    depreciation_quarterly=basis.depreciation_quarterly,
    growth_to_q11=basis.growth_to_q11,
    notes=dict(basis.notes),
  )


def _costs_move_basis(basis: StructuralBasis, patch: Dict[str, float]) -> StructuralBasis:
  return StructuralBasis(
    q1_revenue_quarterly=basis.q1_revenue_quarterly,
    cogs_pct=patch.get("cogs_pct", basis.cogs_pct),
    payroll_quarterly=patch.get("payroll_quarterly", basis.payroll_quarterly),
    rent_quarterly=patch.get("rent_quarterly", basis.rent_quarterly),
    gna_pct=patch.get("gna_pct", basis.gna_pct),
    marketing_pct=patch.get("marketing_pct", basis.marketing_pct),
    interest_quarterly=basis.interest_quarterly,
    depreciation_quarterly=basis.depreciation_quarterly,
    growth_to_q11=basis.growth_to_q11,
    notes=dict(basis.notes),
  )


_OWNER_TITLE_RE_CTL = re.compile(r"owner|principal|founder|managing|partner", re.I)


def payroll_cause_split(financials_json: Dict[str, Any]) -> Dict[str, Any]:
  """PAYROLL CAUSE CLASSIFICATION (Nick-ruled Option A): read the
  payroll basis rows (the canonical rollup's own receipts) and name
  WHY the payroll is what it is, so the walk offers only the honest
  lever for the actual cause. Components:
    owner_annual    - rows whose title matches the one-door owner
                      pattern (the same regex the owner-pay writer uses)
    phasable_annual - inferred_role rows still countable in year 1
                      (months_counted > 0): hire TIMING can remove this
                      without cutting anyone
    staffed_annual  - everything else: named real people + the client's
                      stated rest-of-team (never machine-cut)
  kind = the DOMINANT component ('owner_dominated' / 'planned_hires' /
  'staffed'); ties break toward the least-invasive honest lever
  (owner-draw, then timing, then staffed/no-offer)."""
  rows = (financials_json or {}).get("payroll_basis_people_roles")
  rows = rows if isinstance(rows, list) else []
  owner_annual = 0.0
  phasable_annual = 0.0
  staffed_annual = 0.0
  planned_titles: List[str] = []
  for r in rows:
    if not isinstance(r, dict):
      continue
    amount = _f(r.get("year1_payroll_amount"))
    if amount <= 0:
      continue
    title = str(r.get("role_title") or "")
    source = str(r.get("source") or "").strip().lower()
    if _OWNER_TITLE_RE_CTL.search(title):
      owner_annual += amount
    elif source == "inferred_role":
      phasable_annual += amount
      planned_titles.append(title or "planned hire")
    else:
      staffed_annual += amount
  parts = (
    ("owner_dominated", owner_annual),
    ("planned_hires", phasable_annual),
    ("staffed", staffed_annual),
  )
  kind = max(parts, key=lambda p: p[1])[0] if any(v > 0 for _, v in parts) else "staffed"
  return {
    "kind": kind,
    "owner_annual": round(owner_annual, 2),
    "phasable_annual": round(phasable_annual, 2),
    "staffed_annual": round(staffed_annual, 2),
    "planned_titles": planned_titles,
  }


def _gap(basis: StructuralBasis, thresholds: Thresholds) -> float:
  result = evaluate_structural(basis, thresholds)
  return _f(result.get("gap_quarterly"))


def _pricing_round(
  basis: StructuralBasis,
  thresholds: Thresholds,
  bounds: Dict[str, Any],
  split: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """Price options per the searcher's own quantization: mid
  (1 + (pmax-1)*0.5) and max. Patch specs are ops-field edits."""
  if not split:
    return None
  matched = match_bounds_lines(split, bounds)
  gap_now = _gap(basis, thresholds)
  if gap_now <= 0:
    return None

  def _mults(level: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for line, bl in zip(split, matched):
      key = f"{line['lob']}␟{line['product']}"
      pmax = _effective_pmax(line, bl)  # CW-022 #3: absolute-dollar ceiling
      out[key] = pmax if level == "max" else 1.0 + (pmax - 1.0) * 0.5
    return out

  options = []
  for level, label in (("mid", "meet the market"), ("max", "top of the judged range")):
    mults = _mults(level)
    if all(abs(m - 1.0) < 1e-9 for m in mults.values()):
      continue
    moved = _price_move_basis(basis, split, mults)
    closes = gap_now - _gap(moved, thresholds)
    prices = []
    patch_prices = []
    for line in split:
      key = f"{line['lob']}␟{line['product']}"
      new_price = round(line["unit_price"] * mults[key], 2)
      prices.append({
        "lob": line["lob"], "product": line["product"],
        "from": line["unit_price"], "to": new_price,
      })
      patch_prices.append({
        "lob": line["lob"], "product": line["product"], "unit_price": new_price,
      })
    options.append({
      "id": f"pricing_{level}",
      "label": label,
      # CW-022 #7: a lever that widens the gap is never recommended, and
      # negative closes are SURFACED, not masked to $0 (a negative closes
      # on a price INCREASE is the corrupt-anchor tripwire).
      "recommended": level == "mid" and closes > 0,
      "prices": prices,
      "closes_quarterly": round(closes, 2),
      "widens": closes < -0.005,
      "closes_display": _fmt_money(abs(closes)),
      # current_revenue MUST move with the prices: the engine's Q1
      # anchor (and the legitimate rescale) key on it — a price move
      # without the new anchor would be silently rescaled away.
      "patch": {
        "kind": "ops_prices",
        "prices": patch_prices,
        "current_revenue": round(moved.q1_revenue_quarterly * 4.0, 2),
      },
    })
  if not options:
    return None
  best = max(0.0, max(o["closes_quarterly"] for o in options))
  return {
    "key": ROUND_PRICING,
    "best_closure_quarterly": best,
    "options": options,
    "facts": {
      "lines": [
        {
          "lob": l["lob"], "product": l["product"],
          "current_price": l["unit_price"],
          # CW-022 #3: the displayed believable max is the ABSOLUTE
          # ceiling, never the re-based ratio.
          "believable_max": round(l["unit_price"] * _effective_pmax(l, bl), 2),
        } for l, bl in zip(split, matched)
      ],
    },
  }


def _costs_round(
  basis: StructuralBasis,
  thresholds: Thresholds,
  bounds: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  """Cost-structure options at the judged floors. Patch specs are
  financials-field edits (annual dollars, the fields intake owns)."""
  gap_now = _gap(basis, thresholds)
  if gap_now <= 0:
    return None
  ann_rev = basis.q1_revenue_quarterly * 4.0
  floors = bounds.get("cost_floors") or {}
  team = bounds.get("team") or {}
  fac = bounds.get("facility") or {}
  # Client-asserted floors: costs the client declared committed (signed
  # lease, employment contracts). The walk may NEVER propose cutting
  # them — the corresponding move simply does not exist.
  client_floors = dict(
    ((financials_json or {}).get("_coherence") or {}).get("client_floors") or {}
  )

  moves: Dict[str, Dict[str, Any]] = {}

  # CW-022 #5 DOLLAR-SANITY (the reasoning version, no hardcoded
  # essential-list): a percent-of-revenue floor applied to the live
  # revenue can demand a cut far below what the client has STATED the
  # line actually costs (Fetch & Fluff: 18% x corrupted revenue asked
  # her $17,400 insurance/fuel/maintenance line down to $603). A move
  # cutting a stated line by more than half is a DEEP CUT: it is never
  # recommended, and its wording asks what's inside the line before
  # anything is applied — the client owns what the number means.
  def _deep_cut(current_annual: float, new_annual: float) -> bool:
    return current_annual > 0 and new_annual < 0.5 * current_annual

  mkt_floor = _f(floors.get("marketing_percent_of_revenue_min"), basis.marketing_pct)
  if not client_floors.get("marketing") and mkt_floor < basis.marketing_pct - 1e-6:
    new_annual = round(mkt_floor * ann_rev, 2)
    _cur_annual = basis.marketing_pct * ann_rev
    moves["marketing"] = {
      "basis_patch": {"marketing_pct": mkt_floor},
      "field_patch": {"group": "financials", "field": "marketing_total_year1", "value": new_annual},
      "from_display": _fmt_money(_cur_annual),
      "to_display": _fmt_money(new_annual),
      "deep_cut": _deep_cut(_cur_annual, new_annual),
    }

  # PHASE 4: the COGS move the corner already spends
  # (cogs_percent_of_revenue_min routed clients into walks with no COGS
  # round). BASIS-TAG-AWARE landing: a dollars-basis draft's stated
  # dollars are the source (patch them); ratio/legacy patches the pct
  # and the Recalc re-derives the dollars.
  cogs_floor = _f(floors.get("cogs_percent_of_revenue_min"), basis.cogs_pct)
  if not client_floors.get("cogs") and cogs_floor < basis.cogs_pct - 1e-6:
    new_annual = round(cogs_floor * ann_rev, 2)
    _cur_annual = basis.cogs_pct * ann_rev
    _cogs_dollars = (
      str((financials_json or {}).get("cogs_basis") or "").strip().lower() == "dollars"
    )
    if _cogs_dollars:
      field_patch = {"group": "financials", "field": "cogs_total_year1", "value": new_annual}
      extra = [{"group": "financials", "field": "current_cogs", "value": new_annual}]
    else:
      field_patch = {"group": "financials", "field": "cogs_percent_of_revenue",
                     "value": round(cogs_floor, 6)}
      extra = []
    moves["cogs"] = {
      "basis_patch": {"cogs_pct": cogs_floor},
      "field_patch": field_patch,
      "extra_field_patches": extra,
      "from_display": _fmt_money(_cur_annual),
      "to_display": _fmt_money(new_annual),
      "deep_cut": _deep_cut(_cur_annual, new_annual),
    }

  gna_floor = _f(floors.get("g_and_a_percent_of_revenue_min"), basis.gna_pct)
  if not client_floors.get("gna") and gna_floor < basis.gna_pct - 1e-6:
    new_annual = round(gna_floor * ann_rev, 2)
    _cur_annual = basis.gna_pct * ann_rev
    # patch the MONTHLY field: the sync tail re-derives
    # other_opex_absolute = monthly*12 every turn.
    moves["gna"] = {
      "basis_patch": {"gna_pct": gna_floor},
      "field_patch": {"group": "financials", "field": "other_operating_expense",
                      "value": round(new_annual / 12.0, 2)},
      "from_display": _fmt_money(_cur_annual),
      "to_display": _fmt_money(new_annual),
      "deep_cut": _deep_cut(_cur_annual, new_annual),
    }

  rent_floor_q = _f(fac.get("min_quarterly_rent"))
  if not client_floors.get("rent") and 0 < rent_floor_q < basis.rent_quarterly - 1e-6:
    monthly = round(rent_floor_q / 3.0, 2)
    moves["rent"] = {
      "basis_patch": {"rent_quarterly": rent_floor_q},
      "field_patch": {"group": "financials", "field": "monthly_rent_expense", "value": monthly},
      "from_display": _fmt_money(basis.rent_quarterly) + "/quarter",
      "to_display": _fmt_money(rent_floor_q) + "/quarter",
    }

  # PAYROLL CAUSE-SPLIT (Nick-ruled Option A): the round reads the
  # payroll BASIS ROWS and offers ONLY the honest lever for the actual
  # cause. The old aggregate-delta move materialized as a proportional
  # wage cut across real staff (the cut-insurance disease) and silently
  # NO-OPPED on owner-only teams; it is never offered again.
  #   owner-dominated  -> OWNER-DRAW (one-door, the owner's own choice)
  #   planned hires    -> HIRE TIMING (phase starts later; cuts no one)
  #   existing staff   -> NO cut offer; revenue levers are the closers
  payroll_floor_q = _f(team.get("min_annual_payroll")) / 4.0
  if not client_floors.get("payroll") and 0 < payroll_floor_q < basis.payroll_quarterly - 1e-6:
    needed_annual = round((basis.payroll_quarterly - payroll_floor_q) * 4.0, 2)
    cause = payroll_cause_split(financials_json)
    if cause["kind"] == "owner_dominated" and cause["owner_annual"] > 0:
      _cut = min(needed_annual, cause["owner_annual"])
      _new_owner_annual = round(cause["owner_annual"] - _cut, 2)
      moves["owner_draw"] = {
        "basis_patch": {"payroll_quarterly": round(basis.payroll_quarterly - _cut / 4.0, 2)},
        "field_patch": {"group": "people", "field": "owner_pay_monthly",
                        "value": round(_new_owner_annual / 12.0, 2),
                        "expected_baseline_delta": round(-_cut, 2)},
        "from_display": _fmt_money(cause["owner_annual"] / 12.0) + "/month (your pay)",
        "to_display": _fmt_money(_new_owner_annual / 12.0) + "/month (your pay)",
      }
    elif cause["kind"] == "planned_hires" and cause["phasable_annual"] > 0:
      _cut = min(needed_annual, cause["phasable_annual"])
      moves["hire_timing"] = {
        "basis_patch": {"payroll_quarterly": round(basis.payroll_quarterly - _cut / 4.0, 2)},
        "field_patch": {"group": "people", "field": "phase_planned_hires",
                        "value": {"months_add": 12},
                        "expected_baseline_delta": round(-_cut, 2)},
        "from_display": ", ".join(cause["planned_titles"][:3]) + " starting as planned",
        "to_display": "those hires phased later (year-1 payroll down "
                      + _fmt_money(_cut) + ")",
      }
    # staffed-dominant: deliberately NO move. The tension is surfaced by
    # the wall/narration; the revenue rounds are the honest closers, and
    # a client-volunteered team change is respected via correction.

  if not moves:
    return None

  def _option(ids: List[str], label: str) -> Optional[Dict[str, Any]]:
    picked = {k: moves[k] for k in ids if k in moves}
    if not picked:
      return None
    patch: Dict[str, float] = {}
    fields: List[Dict[str, Any]] = []
    for m in picked.values():
      patch.update(m["basis_patch"])
      fields.append(m["field_patch"])
      fields.extend(m.get("extra_field_patches") or [])
    closes = gap_now - _gap(_costs_move_basis(basis, patch), thresholds)
    deep = any(m.get("deep_cut") for m in picked.values())
    return {
      "id": "costs_" + "_".join(sorted(picked)),
      "label": label + (
        " - only if what's inside those lines can really shrink; tell me "
        "what's in them first" if deep else ""
      ),
      "recommended": False,  # assigned below by reasoning, never hardcoded
      "deep_cut": deep,
      "moves": {k: {kk: vv for kk, vv in m.items() if kk not in ("basis_patch", "extra_field_patches")}
                for k, m in picked.items()},
      "closes_quarterly": round(closes, 2),
      "widens": closes < -0.005,
      "closes_display": _fmt_money(abs(closes)),
      "patch": {"kind": "financials_fields", "fields": fields},
    }

  options = [o for o in (
    _option(list(moves), "right-size all of it"),
    _option(["marketing"], "trim marketing only"),
    _option(["cogs"], "trim direct costs only"),
    _option([k for k in ("marketing", "rent") if k in moves], "marketing and the space, keep the team as-is"),
  ) if o]
  # dedupe identical id sets
  seen = set()
  unique = []
  for o in options:
    if o["id"] in seen:
      continue
    seen.add(o["id"])
    unique.append(o)
  if not unique:
    return None
  # CW-022 #5: the recommendation is REASONED - the largest genuine
  # closure among options that neither widen the gap nor demand a deep
  # cut into a client-stated line. If none qualifies, nothing is
  # recommended and the client chooses (the old code hardcoded the
  # maximal-cut bundle as "the one I'd suggest" by construction).
  _candidates = [o for o in unique if o["closes_quarterly"] > 0 and not o.get("deep_cut")]
  if _candidates:
    max(_candidates, key=lambda o: o["closes_quarterly"])["recommended"] = True
  return {
    "key": ROUND_COSTS,
    "best_closure_quarterly": max(0.0, max(o["closes_quarterly"] for o in unique)),
    "options": unique,
    "facts": {k: {"from": m["from_display"], "to": m["to_display"]} for k, m in moves.items()},
  }


def _volume_round(
  basis: StructuralBasis,
  thresholds: Thresholds,
  bounds: Dict[str, Any],
  split: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """PHASE 4: the volume lever the corner already SPENDS. The corner's
  optimism includes volume_multiplier_max, so clients were routed into
  walks whose gap arithmetic assumed a volume move no round could
  offer (the F&F 'another dog or two' client had no lever). Options at
  the searcher's own quantization: mid and max of the judged believable
  volume ceiling, priced with the corner's own projection math."""
  if not split:
    return None
  matched = match_bounds_lines(split, bounds)
  gap_now = _gap(basis, thresholds)
  if gap_now <= 0:
    return None

  def _mults(level: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for line, bl in zip(split, matched):
      key = f"{line['lob']}␟{line['product']}"
      vmax = _effective_vmax(line, bl)
      out[key] = vmax if level == "max" else 1.0 + (vmax - 1.0) * 0.5
    return out

  options = []
  for level, label in (
    ("mid", "grow the book a believable step"),
    ("max", "fill to the judged demand ceiling"),
  ):
    mults = _mults(level)
    if all(abs(m - 1.0) < 1e-9 for m in mults.values()):
      continue
    moved = _volume_move_basis(basis, split, mults)
    closes = gap_now - _gap(moved, thresholds)
    volumes = []
    patch_volumes = []
    for line in split:
      key = f"{line['lob']}␟{line['product']}"
      m = mults[key]
      volumes.append({
        "lob": line["lob"], "product": line["product"],
        "from_annual_units": round(_f(line.get("annual_units"))),
        "to_annual_units": round(_f(line.get("annual_units")) * m),
      })
      patch_volumes.append(_volume_landing(line, m))
    options.append({
      "id": f"volume_{level}",
      "label": label,
      "recommended": level == "mid" and closes > 0,
      "volumes": volumes,
      "closes_quarterly": round(closes, 2),
      "widens": closes < -0.005,
      "closes_display": _fmt_money(abs(closes)),
      # current_revenue moves with the volume (same anchor law as the
      # price lever); COGS follows by BASIS at apply time - ratio-basis
      # pct holds (the Recalc re-derives dollars), dollars-basis stated
      # dollars scale with the volume ratio (volume carries cost).
      "patch": {
        "kind": "ops_volume",
        "volumes": patch_volumes,
        "current_revenue": round(moved.q1_revenue_quarterly * 4.0, 2),
      },
    })
  if not options:
    return None
  best = max(0.0, max(o["closes_quarterly"] for o in options))
  return {
    "key": ROUND_VOLUME,
    "best_closure_quarterly": best,
    "options": options,
    "facts": {
      "lines": [
        {
          "lob": l["lob"], "product": l["product"],
          "current_annual_units": round(_f(l.get("annual_units"))),
          "believable_max_annual_units": round(_f(l.get("annual_units")) * _effective_vmax(l, bl)),
        } for l, bl in zip(split, matched)
      ],
    },
  }


def _new_lines_round(
  basis: StructuralBasis,
  thresholds: Thresholds,
  bounds: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  """New-line candidates at their judged market caps. These are
  OFFERS, not patches — accepting one routes through the ops edit
  conversation (the existing structure-edit path); the controller only
  computes what each is worth."""
  gap_now = _gap(basis, thresholds)
  if gap_now <= 0:
    return None
  candidates = []
  for nl in bounds.get("new_line_candidates") or []:
    cap = _f((nl or {}).get("q11_quarterly_revenue_max"))
    if cap <= 0:
      continue
    gm_raw = (nl or {}).get("gross_margin_pct")
    if gm_raw is None:
      # CW-021 ruling: no fabricated margin — an unauthored candidate
      # cannot be sized as a lever (its closure would be an invented
      # number). It still appears in roadmap milestones, margin marked
      # unspecified.
      continue
    gm_pct = _f(gm_raw)
    added_rev = cap
    added_cogs = cap * (1.0 - gm_pct)
    # closure: revenue at cap folded straight into the Q11 point
    rev_q11 = basis.q11_revenue() + added_rev
    ebitda_delta = added_rev - added_cogs - added_rev * (basis.gna_pct + basis.marketing_pct)
    floor_delta = thresholds.band_low * added_rev
    closes = max(0.0, ebitda_delta - floor_delta)
    product_name = str((nl or {}).get("product") or "").strip()
    candidates.append({
      "id": "newline_" + (product_name.lower().replace(" ", "_") or "line"),
      "label": f"add {product_name}" if product_name else "add a new line",
      "lob": str((nl or {}).get("lob") or "").strip(),
      "product": product_name,
      "unit_price": _f((nl or {}).get("unit_price")),
      "q11_quarterly_revenue_max": cap,
      "gross_margin_pct": gm_pct,
      "closes_quarterly": round(closes, 2),
      "closes_display": _fmt_money(closes),
      "_rev_q11": rev_q11,
    })
  if not candidates:
    return None
  candidates.sort(key=lambda c: -c["closes_quarterly"])
  return {
    "key": ROUND_NEW_LINES,
    "best_closure_quarterly": sum(c["closes_quarterly"] for c in candidates),
    "options": candidates,
    "offer_only": True,
  }


def plan_rounds(
  *,
  basis: StructuralBasis,
  thresholds: Thresholds,
  bounds: Dict[str, Any],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Dict[str, Any],
  rounds_done: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
  """The next round: largest dollar-gap-closure first among rounds not
  yet walked. Returns None when nothing movable remains."""
  done = set(rounds_done or [])
  split = ops_line_split(ops_json, financials_json)
  rounds = []
  if ROUND_PRICING not in done:
    r = _pricing_round(basis, thresholds, bounds, split)
    if r:
      rounds.append(r)
  if ROUND_VOLUME not in done:
    r = _volume_round(basis, thresholds, bounds, split)
    if r:
      rounds.append(r)
  if ROUND_COSTS not in done:
    r = _costs_round(basis, thresholds, bounds, financials_json)
    if r:
      rounds.append(r)
  if ROUND_NEW_LINES not in done:
    r = _new_lines_round(basis, thresholds, bounds)
    if r:
      rounds.append(r)
  if not rounds:
    return None
  # Actionable rounds first (the client can PICK them); offer-only
  # rounds (new lines, which route back through the ops conversation)
  # only lead when nothing actionable remains. Revenue-side levers
  # (price, volume - the client's own market story) precede cost trims.
  order = {ROUND_PRICING: 0, ROUND_VOLUME: 1, ROUND_NEW_LINES: 2, ROUND_COSTS: 3}
  rounds.sort(key=lambda r: (
    bool(r.get("offer_only")),
    -r["best_closure_quarterly"],
    order.get(r["key"], 9),
  ))
  return rounds[0]


def corner_check(
  *,
  basis: StructuralBasis,
  thresholds: Thresholds,
  bounds: Dict[str, Any],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  """Silent corner-first: the NI-favorable corner of the bounds box on
  the stated-wage basis (consistent with the intake basis on both
  sides). PASS -> guided walk; FAIL -> roadmap."""
  split = ops_line_split(ops_json, financials_json)
  corner_split = []
  for line, bl in zip(split, match_bounds_lines(split, bounds)):
    corner_split.append({
      "q1_revenue_quarterly": line["q1_revenue_quarterly"],
      # CW-022 #3: the corner's optimism uses the same absolute-dollar
      # price ceiling as the pricing round - the ratchet must not widen
      # the corner either.
      "price_multiplier_max": _effective_pmax(line, bl),
      "volume_multiplier_max": _f((bl or {}).get("volume_multiplier_max"), 1.0),
    })
  corner = favorable_corner_basis(
    basis, bounds,
    existing_line_revenue_split=corner_split or None,
    payroll_burden_factor=1.0,
  )
  result = evaluate_structural(corner, thresholds)
  return {
    "passed": bool(result.get("passed")),
    "q11": result.get("q11"),
    "gap_quarterly": result.get("gap_quarterly"),
    "failed": result.get("failed"),
  }


def roadmap_payload(
  *,
  corner: Dict[str, Any],
  eval_result: Dict[str, Any],
  bounds: Dict[str, Any],
) -> Dict[str, Any]:
  """Milestones in the client's own numbers when even the corner
  fails: each unsatisfiable constraint becomes 'what would have to
  become true'."""
  cq = corner.get("q11") or {}
  milestones = []
  lines = bounds.get("existing_lines") or []
  if lines:
    milestones.append({
      "key": "volume_ceiling",
      "title": "a volume ceiling that moves",
      "detail": "standing accounts or channels beyond what the current setup can reach",
    })
  team = bounds.get("team") or {}
  if _f(team.get("min_annual_payroll")) > 0:
    milestones.append({
      "key": "payroll_staging",
      "title": "payroll staged to revenue, not to the plan",
      "detail": f"the believable team floor is {_fmt_money(_f(team.get('min_annual_payroll')))}/yr - and even that floor needs more revenue under it",
    })
  for nl in (bounds.get("new_line_candidates") or [])[:2]:
    cap = _f((nl or {}).get("q11_quarterly_revenue_max"))
    if cap > 0:
      milestones.append({
        "key": f"prove_{str((nl or {}).get('product') or 'channel').strip()}",
        "title": f"prove {str((nl or {}).get('product') or 'a second channel').strip()} with real orders",
        "detail": f"judged potential up to {_fmt_money(cap)}/quarter"
                  + (
                    f" at {round(_f((nl or {}).get('gross_margin_pct')) * 100)}% margin"
                    if (nl or {}).get("gross_margin_pct") is not None
                    else " (margin not yet specified)"
                  )
                  + " - currently an assumption, not revenue",
      })
  return {
    "corner_revenue_display": _fmt_money(_f(cq.get("revenue"))),
    "corner_ebitda_display": _fmt_money(_f(cq.get("ebitda"))),
    "corner_gap_display": _fmt_money(_f(corner.get("gap_quarterly"))),
    "milestones": milestones,
  }


def evaluate_current(
  *,
  financials_json: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  margin_band: Optional[Dict[str, Any]] = None,
  growth_to_q11: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
  """Evaluate the stated configuration. None when no revenue basis
  exists yet (financials still accumulating — nothing to say).
  growth_to_q11: the judged Q1→Q11 multiple (from the engine's own
  proposer) when a growth stamp exists; None falls back to the fence."""
  from client_intake_and_finmo.intake_coherence.evaluator import GROWTH_FENCE_Q11
  basis = basis_from_intake(
    financials_json=financials_json,
    ops_json=ops_json,
    financials_year1_json=financials_year1_json,
    growth_to_q11=float(growth_to_q11) if growth_to_q11 else GROWTH_FENCE_Q11,
  )
  if basis is None:
    return None
  thresholds = thresholds_from_margin_band(margin_band)
  result = evaluate_structural(basis, thresholds)
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
  "STATUS_PENDING", "STATUS_WALKING", "STATUS_CONVERGED",
  "STATUS_PARKED", "STATUS_ROADMAP",
  "ROUND_PRICING", "ROUND_NEW_LINES", "ROUND_COSTS", "ROUND_VOLUME",
  "stable_digest_hash", "ops_line_split", "plan_rounds",
  "corner_check", "roadmap_payload", "evaluate_current",
]
