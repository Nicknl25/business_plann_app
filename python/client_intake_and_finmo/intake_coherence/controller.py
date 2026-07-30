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


def _price_move_basis(
  basis: StructuralBasis,
  split: List[Dict[str, Any]],
  multipliers: Dict[str, float],
) -> StructuralBasis:
  """Basis with per-line price multipliers applied: revenue scales,
  COGS dollars hold (volume held — price is pure margin)."""
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
  # COGS dollars held: pct rescales by revenue ratio.
  ratio = base_rev / new_rev
  return StructuralBasis(
    q1_revenue_quarterly=new_rev,
    cogs_pct=basis.cogs_pct * ratio,
    payroll_quarterly=basis.payroll_quarterly,
    rent_quarterly=basis.rent_quarterly,
    gna_pct=basis.gna_pct,
    marketing_pct=basis.marketing_pct,
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
      pmax = max(1.0, _f((bl or {}).get("price_multiplier_max"), 1.0))
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
      "recommended": level == "mid",
      "prices": prices,
      "closes_quarterly": round(max(0.0, closes), 2),
      "closes_display": _fmt_money(max(0.0, closes)),
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
  best = max(o["closes_quarterly"] for o in options)
  return {
    "key": ROUND_PRICING,
    "best_closure_quarterly": best,
    "options": options,
    "facts": {
      "lines": [
        {
          "lob": l["lob"], "product": l["product"],
          "current_price": l["unit_price"],
          "believable_max": round(
            l["unit_price"] * max(1.0, _f((bl or {}).get("price_multiplier_max"), 1.0)), 2),
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

  moves: Dict[str, Dict[str, Any]] = {}

  mkt_floor = _f(floors.get("marketing_percent_of_revenue_min"), basis.marketing_pct)
  if mkt_floor < basis.marketing_pct - 1e-6:
    new_annual = round(mkt_floor * ann_rev, 2)
    moves["marketing"] = {
      "basis_patch": {"marketing_pct": mkt_floor},
      "field_patch": {"group": "financials", "field": "marketing_total_year1", "value": new_annual},
      "from_display": _fmt_money(basis.marketing_pct * ann_rev),
      "to_display": _fmt_money(new_annual),
    }

  gna_floor = _f(floors.get("g_and_a_percent_of_revenue_min"), basis.gna_pct)
  if gna_floor < basis.gna_pct - 1e-6:
    new_annual = round(gna_floor * ann_rev, 2)
    # patch the MONTHLY field: the sync tail re-derives
    # other_opex_absolute = monthly*12 every turn.
    moves["gna"] = {
      "basis_patch": {"gna_pct": gna_floor},
      "field_patch": {"group": "financials", "field": "other_operating_expense",
                      "value": round(new_annual / 12.0, 2)},
      "from_display": _fmt_money(basis.gna_pct * ann_rev),
      "to_display": _fmt_money(new_annual),
    }

  rent_floor_q = _f(fac.get("min_quarterly_rent"))
  if 0 < rent_floor_q < basis.rent_quarterly - 1e-6:
    monthly = round(rent_floor_q / 3.0, 2)
    moves["rent"] = {
      "basis_patch": {"rent_quarterly": rent_floor_q},
      "field_patch": {"group": "financials", "field": "monthly_rent_expense", "value": monthly},
      "from_display": _fmt_money(basis.rent_quarterly) + "/quarter",
      "to_display": _fmt_money(rent_floor_q) + "/quarter",
    }

  # Team floor is authored in stated-wage terms — the same basis the
  # evaluator reads (people baseline + adjustment + additive owner comp).
  # The machine patch MUST land the panel exactly on the displayed target:
  # target = floor×4 minus whatever owner-comp the evaluator adds back.
  payroll_floor_q = _f(team.get("min_annual_payroll")) / 4.0
  if 0 < payroll_floor_q < basis.payroll_quarterly - 1e-6:
    pb = (basis.notes or {}).get("payroll_basis") or {}
    owner_additive = _f(pb.get("owner_comp_additive"))
    baseline_annual = _f(financials_json.get("baseline_payroll_year1"))
    target_annual = round(max(0.0, payroll_floor_q * 4.0 - owner_additive), 2)
    if baseline_annual > 0:
      # People stays the single source of payroll truth: the lever
      # expresses a client-approved DELTA from the people baseline via
      # payroll_adjustment — the exact field the evaluator adds back —
      # never a rewrite of the baseline or the legacy echo fields.
      # (The old code subtracted RAW owner comp and patched
      # payroll_total_year1; with a corrupted owner comp the clamp
      # produced value 0.0 under a "$65,000/quarter" display —
      # Harborline CW-001.)
      field_patch = {
        "group": "financials", "field": "payroll_adjustment",
        "value": round(target_annual - baseline_annual, 2),
      }
      extra_patches: List[Dict[str, Any]] = []
    else:
      # Legacy drafts with no people baseline keep the paired echo-field
      # contract (sync keeps them together; autocomplete guard keys on
      # current_payroll being set).
      field_patch = {
        "group": "financials", "field": "payroll_total_year1", "value": target_annual,
      }
      extra_patches = [
        {"group": "financials", "field": "current_payroll", "value": target_annual},
      ]
    moves["payroll"] = {
      "basis_patch": {"payroll_quarterly": payroll_floor_q},
      "field_patch": field_patch,
      "extra_field_patches": extra_patches,
      "from_display": _fmt_money(basis.payroll_quarterly) + "/quarter",
      "to_display": _fmt_money(payroll_floor_q) + "/quarter",
    }

  if not moves:
    return None

  def _option(ids: List[str], label: str, recommended: bool) -> Optional[Dict[str, Any]]:
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
    return {
      "id": "costs_" + "_".join(sorted(picked)),
      "label": label,
      "recommended": recommended,
      "moves": {k: {kk: vv for kk, vv in m.items() if kk not in ("basis_patch", "extra_field_patches")}
                for k, m in picked.items()},
      "closes_quarterly": round(max(0.0, closes), 2),
      "closes_display": _fmt_money(max(0.0, closes)),
      "patch": {"kind": "financials_fields", "fields": fields},
    }

  options = [o for o in (
    _option(list(moves), "right-size all of it", True),
    _option(["marketing"], "trim marketing only", False),
    _option([k for k in ("marketing", "rent") if k in moves], "marketing and the space, keep the team as-is", False),
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
  return {
    "key": ROUND_COSTS,
    "best_closure_quarterly": max(o["closes_quarterly"] for o in unique),
    "options": unique,
    "facts": {k: {"from": m["from_display"], "to": m["to_display"]} for k, m in moves.items()},
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
    gm_pct = _f((nl or {}).get("gross_margin_pct"), 0.5)
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
  # only lead when nothing actionable remains.
  order = {ROUND_PRICING: 0, ROUND_NEW_LINES: 1, ROUND_COSTS: 2}
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
      "price_multiplier_max": _f((bl or {}).get("price_multiplier_max"), 1.0),
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
        "detail": f"judged potential up to {_fmt_money(cap)}/quarter at "
                  f"{round(_f((nl or {}).get('gross_margin_pct'), 0.5) * 100)}% margin - currently an assumption, not revenue",
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
  "ROUND_PRICING", "ROUND_NEW_LINES", "ROUND_COSTS",
  "stable_digest_hash", "ops_line_split", "plan_rounds",
  "corner_check", "roadmap_payload", "evaluate_current",
]
