"""RESTRUCTURE SEARCHER — deterministic search over the WHOLE P&L.

The solver's seat in restructure v2: explore every configuration of the
business — per-line volume reallocation (including drops), per-line
pricing, real added lines, team payroll, facility rent, the full cost
shape — INSIDE the executive-authored reality bounds, scored by the
fast evaluator (the pipeline's own math + the gate's own checks).

Strategy (deterministic, no randomness — same bounds + same base plan
=> same winning configuration):
  1. GREEDY COORDINATE DESCENT from the as-stated configuration: sweep
     every dimension's quantized levels, take the move that best
     improves (failed-check count, viability gap, aggressiveness);
     repeat until viable or no move improves.
  2. REFINE-BACK: once viable, walk every dimension back toward the
     as-stated level as far as viability allows — the LEAST-aggressive
     viable design is the most lender-defensible one.

The searcher only SEARCHES. The winning configuration goes to the GPT
solution review and then through the REAL pipeline for the actual
verdict.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_restructure.fast_evaluator import (  # type: ignore
  build_fast_finmo,
  score_viability,
)

_MAX_SWEEPS = 8
_MAX_EVALS = 600


# ---------------------------------------------------------------- candidates

def _key(v: Any) -> str:
  return str(v or "").strip().casefold()


def _glide(q: int, m11: float, m20: float) -> float:
  if q <= 11:
    return 1.0 + (m11 - 1.0) * ((q - 1) / 10.0)
  return m11 + (m20 - m11) * ((q - 11) / 9.0)


def _level_glide(q: int, start: float, target: float, land_q: int) -> float:
  """Amount glide: stated start at Q1, linear to target by land_q, flat after."""
  if q <= 1:
    return start
  if q >= land_q:
    return target
  return start + (target - start) * ((q - 1) / float(land_q - 1))


def synthesize_new_line_rows(
  templates: Dict[str, Dict[str, Any]],
  rev_rows: List[Any],
  *,
  lob: str,
  product: str,
  unit_price: float,
  q11_quarterly_revenue: float,
) -> List[Dict[str, Any]]:
  """Build a contract-valid driver-row triple for a NEW revenue line.

  The FinmoModelInputContract groups revenue rows by revenue_slot_key
  (lob_N_product_M, exactly one row per canonical driver) — the new
  line needs its OWN slot, its own identity fields, and none of the
  template's derived-driver metadata (a payroll-derived Capacity row
  must not make the new line born-derived)."""
  if unit_price <= 0.0 or q11_quarterly_revenue <= 0.0 or len(templates) != 3:
    return []
  max_lob = 0
  for row in rev_rows:
    if isinstance(row, dict):
      key = str(row.get("revenue_slot_key") or "")
      if key.startswith("lob_"):
        try:
          max_lob = max(max_lob, int(key.split("_")[1]))
        except (ValueError, IndexError):
          pass
  slot_key = f"lob_{max_lob + 1}_product_1"
  cap11 = q11_quarterly_revenue / unit_price
  n_slots = len(templates["Unit Price"].get("values") or []) or 21
  series: Dict[str, List[float]] = {"Unit Price": [], "Capacity": [], "Utilization": []}
  for q in range(n_slots):
    if q <= 1:
      for d in series:
        series[d].append(0.0)
      continue
    ramp = min(1.0, (q - 1) / 10.0)
    series["Unit Price"].append(round(unit_price, 6))
    series["Capacity"].append(round(cap11 * ramp, 6))
    series["Utilization"].append(1.0)
  out: List[Dict[str, Any]] = []
  for d, tpl in templates.items():
    new_row = copy.deepcopy(tpl)
    new_row["lob"] = lob or "New"
    new_row["product"] = product or "New Line"
    new_row["revenue_slot_key"] = slot_key
    new_row["values"] = series[d]
    new_row["placeholder_lob"] = lob or "New"
    new_row["placeholder_product"] = product or "New Line"
    new_row["derived_driver"] = None
    new_row["payroll_supported_capacity"] = None
    new_row["capacity_shaping"] = None
    new_row["controller_write"] = True
    # The new line is its own lever set — an adjustable cell for the
    # joint solver, never a collision with the template's lever id.
    new_row["lever_id"] = f"revenue::{lob or 'New'}::{product or 'New Line'}::{d}"
    for idx_key, idx_val in (("lob_slot_index", max_lob), ("product_slot_index", 0)):
      if idx_key in new_row:
        new_row[idx_key] = idx_val
    out.append(new_row)
  return out


def _base_line_revenue_series(base_model_input: Dict[str, Any]) -> Dict[str, List[float]]:
  """Per-line quarterly revenue (cap x util x price) off the base rows."""
  groups: Dict[str, Dict[str, List[Any]]] = {}
  for row in ((base_model_input.get("sections") or {}).get("revenue") or []):
    if not isinstance(row, dict):
      continue
    lk = f"{_key(row.get('lob'))}/{_key(row.get('product'))}"
    groups.setdefault(lk, {})[str(row.get("driver") or "").strip()] = row.get("values") or []
  out: Dict[str, List[float]] = {}
  for lk, drv in groups.items():
    series: List[float] = []
    for q in range(21):
      try:
        c = float((drv.get("Capacity") or [])[q])
        u = float((drv.get("Utilization") or [])[q])
        p = float((drv.get("Unit Price") or [])[q])
        series.append(c * u * p)
      except (TypeError, ValueError, IndexError):
        series.append(0.0)
    out[lk] = series
  return out


def blended_cogs_ratio(
  *,
  base_line_rev: Dict[str, List[float]],
  base_cogs_row: List[float],
  candidate: Dict[str, Any],
  line_margins: Dict[str, float],
  q: int,
) -> Optional[float]:
  """The candidate mix's COGS ratio at quarter q, from per-line margins.

  CALIBRATED TO STATED REALITY: the executive's per-line margins are
  applied RELATIVELY — at the base mix the blend reproduces the stated
  COGS row exactly (a per-quarter normalization factor), so mix shifts
  move the ratio without re-inventing the baseline. New lines carry
  their authored margin absolutely (there is no stated baseline for a
  line that does not exist yet)."""
  lines = candidate.get("lines") or {}
  base_total = 0.0
  base_weighted = 0.0
  cand_total = 0.0
  cand_weighted = 0.0
  for lk, series in base_line_rev.items():
    margin = line_margins.get(lk)
    if margin is None:
      return None
    rev_q = series[q] if q < len(series) else 0.0
    cogs_pct = max(0.0, 1.0 - float(margin))
    base_total += rev_q
    base_weighted += rev_q * cogs_pct
    cfg = lines.get(lk) or {}
    v11 = float(cfg.get("volume_m11") if cfg.get("volume_m11") is not None else 1.0)
    v20 = float(cfg.get("volume_m20") if cfg.get("volume_m20") is not None else v11)
    p11 = float(cfg.get("price_m11") or 1.0)
    p20 = float(cfg.get("price_m20") or p11)
    cand_rev_q = rev_q * _glide(q, v11, v20) * _glide(q, p11, p20)
    cand_total += cand_rev_q
    # Price-up dilutes the line's COGS ratio (same physical cost over a
    # higher price) — divide the ratio by the price glide.
    cand_weighted += cand_rev_q * (cogs_pct / max(1e-9, _glide(q, p11, p20)))
  if base_total <= 0 or cand_total < 0:
    return None
  blend0 = base_weighted / base_total
  try:
    stated_q = float(base_cogs_row[q])
  except (TypeError, ValueError, IndexError):
    return None
  factor = (stated_q / blend0) if blend0 > 1e-9 else 1.0
  new_total = cand_total
  new_weighted = cand_weighted * factor
  for nl in (candidate.get("new_lines") or []):
    target = float((nl or {}).get("q11_quarterly_revenue") or 0.0)
    price = float((nl or {}).get("unit_price") or 0.0)
    if target <= 0.0 or price <= 0.0 or q <= 1:
      continue
    ramp = min(1.0, (q - 1) / 10.0)
    rev_nq = target * ramp
    margin_n = float((nl or {}).get("gross_margin_pct") or 0.50)
    new_total += rev_nq
    new_weighted += rev_nq * max(0.0, 1.0 - margin_n)
  if new_total <= 0:
    return None
  return max(0.0, min(0.99, new_weighted / new_total))


def apply_candidate(
  base_model_input: Dict[str, Any],
  candidate: Dict[str, Any],
  *,
  line_margins: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
  """Materialize a candidate configuration as direct row edits on a copy
  of the base model_input. Q1 always stays stated reality."""
  mi = copy.deepcopy(base_model_input)
  sections = mi.get("sections") or {}
  rev_rows = sections.get("revenue") or []

  lines = candidate.get("lines") or {}

  # The build's derived-driver policy REGENERATES the Payroll row from
  # the stored headcount schedule, which would discard the candidate's
  # labor-coupled payroll. Candidates that change the P&L drop that
  # policy so their payroll rows stand (the empty base candidate keeps
  # it — base evaluation stays byte-exact vs the real pipeline).
  if candidate:
    for holder_key in ("derived_driver_policies", "derived_driver_runtime"):
      holder = mi.get(holder_key)
      if isinstance(holder, dict):
        holder.pop("expenses::Payroll", None)

  # LABOR PHYSICS — the real pipeline couples capacity and payroll (a
  # labor-bound business cannot produce 1.5x volume with the same
  # team; Handler C derives capacity FROM payroll). The evaluator must
  # model the same coupling or the search designs plans the real
  # system correctly refuses to materialize: per quarter, compute the
  # base-revenue-weighted VOLUME multiplier (price moves are margin,
  # not labor) and scale the Payroll row by it.
  base_line_rev: Dict[str, List[float]] = {}
  groups: Dict[str, Dict[str, List[Any]]] = {}
  for row in ((base_model_input.get("sections") or {}).get("revenue") or []):
    if not isinstance(row, dict):
      continue
    lk = f"{_key(row.get('lob'))}/{_key(row.get('product'))}"
    groups.setdefault(lk, {})[str(row.get("driver") or "").strip()] = row.get("values") or []
  for lk, drv in groups.items():
    series: List[float] = []
    for q in range(21):
      try:
        c = float((drv.get("Capacity") or [])[q])
        u = float((drv.get("Utilization") or [])[q])
        p = float((drv.get("Unit Price") or [])[q])
        series.append(c * u * p)
      except (TypeError, ValueError, IndexError):
        series.append(0.0)
    base_line_rev[lk] = series
  labor_multiplier: List[float] = [1.0] * 21
  for q in range(2, 21):
    total = 0.0
    scaled = 0.0
    for lk, series in base_line_rev.items():
      rev_q = series[q] if q < len(series) else 0.0
      total += rev_q
      cfg = lines.get(lk) or {}
      v11 = float(cfg.get("volume_m11") if cfg.get("volume_m11") is not None else 1.0)
      v20 = float(cfg.get("volume_m20") if cfg.get("volume_m20") is not None else v11)
      scaled += rev_q * _glide(q, v11, v20)
    labor_multiplier[q] = (scaled / total) if total > 0 else 1.0
  for row in rev_rows:
    if not isinstance(row, dict):
      continue
    driver = str(row.get("driver") or "").strip()
    if driver not in ("Unit Price", "Capacity"):
      continue
    line_key = f"{_key(row.get('lob'))}/{_key(row.get('product'))}"
    cfg = lines.get(line_key)
    if not isinstance(cfg, dict):
      continue
    if driver == "Unit Price":
      m11 = float(cfg.get("price_m11") or 1.0)
      m20 = float(cfg.get("price_m20") or m11)
    else:
      m11 = float(cfg.get("volume_m11") if cfg.get("volume_m11") is not None else 1.0)
      m20 = float(cfg.get("volume_m20") if cfg.get("volume_m20") is not None else m11)
    if abs(m11 - 1.0) <= 1e-9 and abs(m20 - 1.0) <= 1e-9:
      continue
    vals = row.get("values")
    if not isinstance(vals, list):
      continue
    for q in range(2, min(21, len(vals))):
      try:
        vals[q] = round(float(vals[q]) * _glide(q, m11, m20), 6)
      except (TypeError, ValueError):
        pass

  # New lines: contract-valid driver triples in their own slot.
  new_lines = [nl for nl in (candidate.get("new_lines") or []) if float(nl.get("q11_quarterly_revenue") or 0.0) > 0.0]
  if new_lines:
    templates: Dict[str, Dict[str, Any]] = {}
    for row in rev_rows:
      if isinstance(row, dict):
        d = str(row.get("driver") or "").strip()
        if d in ("Unit Price", "Capacity", "Utilization") and d not in templates:
          templates[d] = row
    for nl in new_lines:
      rev_rows.extend(synthesize_new_line_rows(
        templates, rev_rows,
        lob=str(nl.get("lob") or "New"),
        product=str(nl.get("product") or "New Line"),
        unit_price=float(nl.get("unit_price") or 0.0),
        q11_quarterly_revenue=float(nl.get("q11_quarterly_revenue") or 0.0),
      ))

  # Expense rows. Ratios (COGS/Marketing/G&A) glide to the candidate
  # level by Q11; amounts (Payroll quarterly, Lease quarterly) glide to
  # the candidate level by Q5 (a restructure executes fast).
  ratio_targets = {
    "Cost of Goods Sold": candidate.get("cogs_pct"),
    "Marketing": candidate.get("marketing_pct"),
    "General & Administrative": candidate.get("g_and_a_pct"),
  }
  amount_targets = {
    "Payroll": (
      float(candidate["annual_payroll"]) / 4.0
      if candidate.get("annual_payroll") is not None else None
    ),
    "Lease": (
      float(candidate["quarterly_rent"])
      if candidate.get("quarterly_rent") is not None else None
    ),
  }
  # PER-LINE MARGIN VISION — when the executive authored each line's
  # true gross margin, the COGS row is RECOMPUTED from the candidate's
  # mix (calibrated so the base mix reproduces the stated row exactly).
  # A 55%-margin line now LOOKS like a 55%-margin line to the solver —
  # a blended average hides exactly the signal a mix restructure needs.
  _blend_active = bool(candidate) and isinstance(line_margins, dict) and bool(line_margins)
  _base_cogs_row: List[float] = []
  if _blend_active:
    for row in ((base_model_input.get("sections") or {}).get("expenses") or []):
      if isinstance(row, dict) and str(row.get("label") or "").strip() == "Cost of Goods Sold":
        _base_cogs_row = list(row.get("values") or [])
        break
    _blend_active = bool(_base_cogs_row)
  _blend_base_line_rev = _base_line_revenue_series(base_model_input) if _blend_active else {}

  for row in (sections.get("expenses") or []):
    if not isinstance(row, dict):
      continue
    label = str(row.get("label") or "").strip()
    vals = row.get("values")
    if not isinstance(vals, list) or len(vals) < 3:
      continue
    if label == "Cost of Goods Sold" and _blend_active:
      for q in range(2, min(21, len(vals))):
        blended = blended_cogs_ratio(
          base_line_rev=_blend_base_line_rev,
          base_cogs_row=_base_cogs_row,
          candidate=candidate,
          line_margins=line_margins or {},
          q=q,
        )
        if blended is not None:
          vals[q] = round(blended, 6)
    elif label in ratio_targets and ratio_targets[label] is not None:
      target = float(ratio_targets[label])
      try:
        start = float(vals[1])
      except (TypeError, ValueError):
        continue
      for q in range(2, min(21, len(vals))):
        vals[q] = round(_level_glide(q, start, target, 11), 6)
    elif label == "Payroll":
      # Labor physics: the (possibly resized) team scales with volume.
      # Candidate payroll level = the team at TODAY'S volume; the
      # per-quarter labor multiplier carries it to the designed volume.
      target_q = amount_targets.get("Payroll")
      try:
        start = float(vals[1])
      except (TypeError, ValueError):
        continue
      for q in range(2, min(21, len(vals))):
        try:
          base_q = float(vals[q])
        except (TypeError, ValueError):
          continue
        level_q = (
          _level_glide(q, start, float(target_q), 5)
          if target_q is not None else base_q
        )
        vals[q] = round(level_q * labor_multiplier[q], 6)
    elif label == "Lease" and amount_targets.get("Lease") is not None:
      target = float(amount_targets["Lease"])
      try:
        start = float(vals[1])
      except (TypeError, ValueError):
        continue
      for q in range(2, min(21, len(vals))):
        vals[q] = round(_level_glide(q, start, target, 5), 6)
  return mi


# ---------------------------------------------------------------- scoring

def _gap_scalar(score: Dict[str, Any]) -> float:
  """Scalar viability gap from the landed margins (for ordering moves;
  the binding checks themselves decide viable/not)."""
  landed = score.get("landed") or {}
  q11 = landed.get("q11") or {}
  q20 = landed.get("q20") or {}
  eb11 = float(q11.get("ebitda_margin") or 0.0)
  ni11 = float(q11.get("net_income_margin") or 0.0)
  eb20 = float(q20.get("ebitda_margin") or 0.0)
  gap = 0.0
  gap += max(0.0, -eb11)
  gap += max(0.0, 0.02 - ni11)
  gap += max(0.0, (eb11 - eb20) - 0.01)
  if not (q11.get("revenue") or 0):
    gap += 10.0
  return round(gap, 6)


def _aggressiveness(candidate: Dict[str, Any], base: Dict[str, Any]) -> float:
  """How far the candidate strays from as-stated — lower is more
  lender-defensible. Sum of absolute relative moves."""
  cost = 0.0
  for cfg in (candidate.get("lines") or {}).values():
    cost += abs(float(cfg.get("price_m11") or 1.0) - 1.0)
    cost += abs(float(cfg.get("volume_m11") if cfg.get("volume_m11") is not None else 1.0) - 1.0) * 0.5
  for nl in (candidate.get("new_lines") or []):
    if float(nl.get("q11_quarterly_revenue") or 0.0) > 0.0:
      # A real added line reads as a turnaround story, not a distress
      # signal — weighted comparably to a moderate cost move so revenue
      # restructures compete fairly with cost compression.
      cost += 0.30
  for key, base_key in (
    ("annual_payroll", "annual_payroll"),
    ("quarterly_rent", "quarterly_rent"),
  ):
    cv, bv = candidate.get(key), base.get(base_key)
    if cv is not None and bv:
      cost += abs(float(cv) - float(bv)) / max(1.0, abs(float(bv)))
  for key, base_key in (
    ("cogs_pct", "cogs_pct"), ("marketing_pct", "marketing_pct"), ("g_and_a_pct", "g_and_a_pct"),
  ):
    cv, bv = candidate.get(key), base.get(base_key)
    if cv is not None and bv is not None:
      cost += abs(float(cv) - float(bv)) * 2.0
  return round(cost, 6)


def has_revenue_move(candidate: Dict[str, Any]) -> bool:
  """True when the candidate changes the revenue side at all (pricing,
  volume/mix, or an added line)."""
  for cfg in (candidate.get("lines") or {}).values():
    if not isinstance(cfg, dict):
      continue
    for key, neutral in (("price_m11", 1.0), ("price_m20", 1.0), ("volume_m11", 1.0), ("volume_m20", 1.0)):
      v = cfg.get(key)
      if v is not None and abs(float(v) - neutral) > 1e-9:
        return True
  for nl in (candidate.get("new_lines") or []):
    if float((nl or {}).get("q11_quarterly_revenue") or 0.0) > 0.0:
      return True
  return False


def _objective(
  score: Dict[str, Any],
  candidate: Dict[str, Any],
  base_levels: Dict[str, Any],
  *,
  require_revenue_move: bool = False,
) -> Tuple[int, float, float]:
  # The reviewer's "cost compression alone is not a credible story"
  # rejection, encoded: a design with no revenue-side move carries a
  # synthetic failing check, so the solve must build around revenue.
  missing_story = 1 if (require_revenue_move and not has_revenue_move(candidate)) else 0
  return (
    len(score.get("failed_binding") or []) + missing_story,
    _gap_scalar(score),
    _aggressiveness(candidate, base_levels),
  )


# ---------------------------------------------------------------- search

def _base_levels(base_model_input: Dict[str, Any]) -> Dict[str, Any]:
  """As-stated levels read off the base model_input (Q1 column)."""
  out: Dict[str, Any] = {}
  for row in ((base_model_input.get("sections") or {}).get("expenses") or []):
    if not isinstance(row, dict):
      continue
    label = str(row.get("label") or "").strip()
    vals = row.get("values") or []
    try:
      v1 = float(vals[1])
    except (TypeError, ValueError, IndexError):
      continue
    if label == "Payroll":
      out["annual_payroll"] = v1 * 4.0
    elif label == "Lease":
      out["quarterly_rent"] = v1
    elif label == "Cost of Goods Sold":
      out["cogs_pct"] = v1
    elif label == "Marketing":
      out["marketing_pct"] = v1
    elif label == "General & Administrative":
      out["g_and_a_pct"] = v1
  return out


def _levels(lo: float, hi: float, n: int = 4) -> List[float]:
  if hi <= lo + 1e-12:
    return [lo]
  return [round(lo + (hi - lo) * i / (n - 1), 6) for i in range(n)]


def line_margins_from_bounds(bounds: Dict[str, Any]) -> Dict[str, float]:
  """Per-line-key gross margins when the executive authored ALL of them
  (partial margins would blend fact with guess — then none are used)."""
  out: Dict[str, float] = {}
  for line in (bounds.get("existing_lines") or []):
    margin = line.get("gross_margin_pct")
    if margin is None:
      return {}
    out[f"{_key(line.get('lob'))}/{_key(line.get('product'))}"] = float(margin)
  return out


def _dimensions(
  bounds: Dict[str, Any],
  base_levels: Dict[str, Any],
  *,
  payroll_burden_factor: float = 1.0,
  margins_active: bool = False,
) -> List[Dict[str, Any]]:
  """Quantized search dimensions from the validated bounds. Each is
  {name, path, levels, neutral}."""
  dims: List[Dict[str, Any]] = []
  for line in (bounds.get("existing_lines") or []):
    lk = f"{_key(line.get('lob'))}/{_key(line.get('product'))}"
    pmax = float(line.get("price_multiplier_max") or 1.0)
    vmax = float(line.get("volume_multiplier_max") or 1.0)
    price_levels = sorted({1.0, round(1.0 + (pmax - 1.0) * 0.5, 4), pmax})
    vol_levels = {1.0, round(min(vmax, 1.5), 4), vmax, 0.75, 0.5}
    if bool(line.get("can_drop")):
      vol_levels.add(0.0)
    vol_levels = sorted(v for v in vol_levels if v <= vmax + 1e-9)
    dims.append({"name": f"price:{lk}", "kind": "line_price", "line": lk, "levels": price_levels, "neutral": 1.0})
    dims.append({"name": f"volume:{lk}", "kind": "line_volume", "line": lk, "levels": vol_levels, "neutral": 1.0})
  for i, nl in enumerate(bounds.get("new_line_candidates") or []):
    rev_max = float(nl.get("q11_quarterly_revenue_max") or 0.0)
    dims.append({
      "name": f"newline:{_key(nl.get('product'))}",
      "kind": "new_line", "index": i, "spec": nl,
      "levels": [0.0, round(rev_max * 0.5, 2), rev_max],
      "neutral": 0.0,
    })
  team = bounds.get("team") or {}
  # The executive authors team bounds in STATED-WAGE terms; the payroll
  # row is LOADED cost (wages + burden). Scale the bounds into the row
  # basis so the floor forbids exactly what the executive forbade.
  _bf = max(1.0, min(2.0, float(payroll_burden_factor or 1.0)))
  dims.append({
    "name": "annual_payroll", "kind": "scalar", "field": "annual_payroll",
    "levels": _levels(float(team.get("min_annual_payroll") or 0.0) * _bf,
                      max(float(team.get("min_annual_payroll") or 0.0) * _bf,
                          float(team.get("max_annual_payroll") or 0.0) * _bf,
                          float(base_levels.get("annual_payroll") or 0.0))),
    "neutral": base_levels.get("annual_payroll"),
  })
  fac = bounds.get("facility") or {}
  dims.append({
    "name": "quarterly_rent", "kind": "scalar", "field": "quarterly_rent",
    "levels": _levels(float(fac.get("min_quarterly_rent") or 0.0),
                      max(float(fac.get("min_quarterly_rent") or 0.0),
                          float(fac.get("max_quarterly_rent") or 0.0),
                          float(base_levels.get("quarterly_rent") or 0.0))),
    "neutral": base_levels.get("quarterly_rent"),
  })
  floors = bounds.get("cost_floors") or {}
  # With per-line margins active, the MIX owns the COGS ratio (the
  # blend recompute) — the scalar COGS lever would fight it.
  _cost_fields = (
    ("marketing_pct", "marketing_percent_of_revenue_min"),
    ("g_and_a_pct", "g_and_a_percent_of_revenue_min"),
  ) if margins_active else (
    ("cogs_pct", "cogs_percent_of_revenue_min"),
    ("marketing_pct", "marketing_percent_of_revenue_min"),
    ("g_and_a_pct", "g_and_a_percent_of_revenue_min"),
  )
  for field, floor_key in _cost_fields:
    base_v = float(base_levels.get(field) or 0.0)
    floor_v = float(floors.get(floor_key) or 0.0)
    hi = max(base_v, floor_v)
    lo = min(floor_v, hi)
    dims.append({
      "name": field, "kind": "scalar", "field": field,
      "levels": sorted({round(lo, 6), round((lo + hi) / 2.0, 6), round(hi, 6)}),
      "neutral": base_levels.get(field),
    })
  return dims


def _set_dim(candidate: Dict[str, Any], dim: Dict[str, Any], level: float) -> Dict[str, Any]:
  c = copy.deepcopy(candidate)
  kind = dim["kind"]
  if kind == "line_price":
    cfg = c.setdefault("lines", {}).setdefault(dim["line"], {})
    cfg["price_m11"] = level
    cfg["price_m20"] = level
  elif kind == "line_volume":
    cfg = c.setdefault("lines", {}).setdefault(dim["line"], {})
    cfg["volume_m11"] = level
    cfg["volume_m20"] = level
  elif kind == "new_line":
    spec = dim["spec"]
    nls = c.setdefault("new_lines", [])
    while len(nls) <= dim["index"]:
      nls.append({})
    nls[dim["index"]] = {
      "lob": spec.get("lob"), "product": spec.get("product"),
      "unit_price": spec.get("unit_price"),
      "gross_margin_pct": spec.get("gross_margin_pct"),
      "q11_quarterly_revenue": level,
    }
  else:
    c[dim["field"]] = level
  return c


def _get_dim(candidate: Dict[str, Any], dim: Dict[str, Any]) -> Optional[float]:
  kind = dim["kind"]
  if kind == "line_price":
    return ((candidate.get("lines") or {}).get(dim["line"]) or {}).get("price_m11", 1.0)
  if kind == "line_volume":
    cfg = (candidate.get("lines") or {}).get(dim["line"]) or {}
    return cfg.get("volume_m11", 1.0) if cfg.get("volume_m11") is not None else 1.0
  if kind == "new_line":
    nls = candidate.get("new_lines") or []
    if dim["index"] < len(nls):
      return float((nls[dim["index"]] or {}).get("q11_quarterly_revenue") or 0.0)
    return 0.0
  return candidate.get(dim["field"])


def search_viable_configuration(
  *,
  base_model_input: Dict[str, Any],
  bounds: Dict[str, Any],
  business_naics_6: Optional[str] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  require_revenue_move: bool = False,
) -> Dict[str, Any]:
  """Greedy coordinate descent + refine-back. Returns::

    {found: bool, candidate, score, evals, trace: [..]}

  ``require_revenue_move``: the reviewer's structural requirement — a
  solution counts only if it includes at least one revenue-side move.
  """
  base_lv = _base_levels(base_model_input)
  line_margins = line_margins_from_bounds(bounds)
  stated_wages = 0.0
  try:
    stated_wages = float((financials_json or {}).get("payroll_total_year1") or 0.0)
  except (TypeError, ValueError):
    stated_wages = 0.0
  payroll_burden_factor = (
    (float(base_lv.get("annual_payroll") or 0.0) / stated_wages)
    if stated_wages > 0 and float(base_lv.get("annual_payroll") or 0.0) > 0 else 1.0
  )
  dims = _dimensions(
    bounds, base_lv,
    payroll_burden_factor=payroll_burden_factor,
    margins_active=bool(line_margins),
  )
  evals = 0
  trace: List[str] = []
  cache: Dict[str, Any] = {}

  def _evaluate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    nonlocal evals
    import json as _json
    key = _json.dumps(candidate, sort_keys=True, default=str)
    if key in cache:
      return cache[key]
    evals += 1
    mi = apply_candidate(base_model_input, candidate, line_margins=line_margins or None)
    try:
      finmo = build_fast_finmo(mi)
      score = score_viability(
        model_input_json=mi, finmo_json=finmo,
        business_naics_6=business_naics_6, ops_json=ops_json,
        financials_json=financials_json, planning_mode=planning_mode,
      )
    except Exception as exc:  # noqa: BLE001 — a broken candidate must LOSE
      # to every scoreable candidate: 99 pseudo-failures keeps the
      # lexicographic objective from ever preferring it.
      score = {
        "viable_pnl": False,
        "failed_binding": ["evaluation_error"] * 99,
        "checks": {}, "landed": {},
        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
      }
    score.pop("finmo_json", None)
    cache[key] = score
    return score

  def _solved(cand: Dict[str, Any], sc: Dict[str, Any]) -> bool:
    return bool(sc.get("viable_pnl")) and (
      not require_revenue_move or has_revenue_move(cand)
    )

  current: Dict[str, Any] = {}
  current_score = _evaluate(current)
  current_obj = _objective(current_score, current, base_lv, require_revenue_move=require_revenue_move)
  trace.append(f"start: failed={current_score.get('failed_binding')} gap={_gap_scalar(current_score)}")

  # Phase 1 — greedy descent toward viability.
  for sweep in range(_MAX_SWEEPS):
    if _solved(current, current_score) or evals >= _MAX_EVALS:
      break
    best_move = None
    for dim in dims:
      cur_level = _get_dim(current, dim)
      for level in dim["levels"]:
        if cur_level is not None and abs(float(level) - float(cur_level)) <= 1e-9:
          continue
        cand = _set_dim(current, dim, float(level))
        sc = _evaluate(cand)
        obj = _objective(sc, cand, base_lv, require_revenue_move=require_revenue_move)
        if best_move is None or obj < best_move[0]:
          best_move = (obj, dim["name"], level, cand, sc)
        if evals >= _MAX_EVALS:
          break
      if evals >= _MAX_EVALS:
        break
    if best_move is None or best_move[0] >= current_obj:
      trace.append(f"sweep {sweep + 1}: no improving move — exhausted")
      break
    current_obj, name, level, current, current_score = (
      best_move[0], best_move[1], best_move[2], best_move[3], best_move[4]
    )
    trace.append(
      f"sweep {sweep + 1}: {name} -> {level} | failed={current_score.get('failed_binding')} "
      f"gap={_gap_scalar(current_score)}"
    )

  # LEAN-END SNAPSHOT — the configuration at the moment viability was
  # first reached (before refine-back walks toward as-stated). Recorded
  # so minimal-change vs lean-end divergence is visible in the audit.
  candidate_first_viable = (
    copy.deepcopy(current) if _solved(current, current_score) else None
  )
  landed_first_viable = (
    copy.deepcopy((current_score or {}).get("landed"))
    if _solved(current, current_score) else None
  )

  # Phase 2 — refine back toward as-stated while the solution holds
  # (viability AND, when required, the revenue story).
  if _solved(current, current_score):
    improved = True
    guard = 0
    while improved and guard < 4 and evals < _MAX_EVALS:
      improved = False
      guard += 1
      for dim in dims:
        cur_level = _get_dim(current, dim)
        neutral = dim.get("neutral")
        if cur_level is None or neutral is None:
          continue
        toward = [
          lv for lv in dim["levels"]
          if abs(float(lv) - float(neutral)) < abs(float(cur_level) - float(neutral)) - 1e-9
        ]
        toward.sort(key=lambda lv: abs(float(lv) - float(neutral)))
        for level in toward:
          cand = _set_dim(current, dim, float(level))
          sc = _evaluate(cand)
          if _solved(cand, sc):
            current, current_score = cand, sc
            improved = True
            trace.append(f"refine: {dim['name']} back to {level} (still viable)")
            break

  return {
    "found": _solved(current, current_score),
    "candidate": current,
    "score": current_score,
    "candidate_first_viable": candidate_first_viable,
    "landed_first_viable": landed_first_viable,
    "base_levels": base_lv,
    "line_margins": line_margins,
    "payroll_burden_factor": payroll_burden_factor,
    "evals": evals,
    "trace": trace,
  }


def candidate_to_directive(
  candidate: Dict[str, Any],
  bounds: Dict[str, Any],
  base_levels: Dict[str, Any],
  *,
  overall_rationale: str = "",
  base_model_input: Optional[Dict[str, Any]] = None,
  line_margins: Optional[Dict[str, float]] = None,
  payroll_burden_factor: float = 1.0,
) -> Dict[str, Any]:
  """Translate the winning configuration into the restructure directive
  the existing consumption wiring (registry -> initial grid) executes."""
  lines_out: List[Dict[str, Any]] = []
  by_key = {
    f"{_key(l.get('lob'))}/{_key(l.get('product'))}": l
    for l in (bounds.get("existing_lines") or [])
  }
  for lk, cfg in (candidate.get("lines") or {}).items():
    spec = by_key.get(lk) or {}
    v11 = cfg.get("volume_m11")
    v20 = cfg.get("volume_m20", v11)
    p11 = float(cfg.get("price_m11") or 1.0)
    p20 = float(cfg.get("price_m20") or p11)
    volume_changed = v11 is not None and (
      abs(float(v11) - 1.0) > 1e-9 or abs(float(v20 or 1.0) - 1.0) > 1e-9
    )
    price_changed = abs(p11 - 1.0) > 1e-9 or abs(p20 - 1.0) > 1e-9
    if volume_changed or price_changed:
      lines_out.append({
        "lob": spec.get("lob") or lk.split("/")[0],
        "product": spec.get("product") or lk.split("/")[-1],
        "volume_multiplier_q11": float(v11) if v11 is not None else 1.0,
        "volume_multiplier_q20": float(v20 if v20 is not None else (v11 if v11 is not None else 1.0)),
        "price_multiplier_q11": p11,
        "price_multiplier_q20": p20,
        "rationale": "restructure search: reallocated toward the viable mix",
      })
  new_lines_out: List[Dict[str, Any]] = []
  for nl in (candidate.get("new_lines") or []):
    target = float((nl or {}).get("q11_quarterly_revenue") or 0.0)
    if target <= 0.0:
      continue
    new_lines_out.append({
      "lob": nl.get("lob"), "product": nl.get("product"),
      "unit_price": nl.get("unit_price"),
      "q11_quarterly_revenue_target": target,
      "gross_margin_pct": nl.get("gross_margin_pct"),
      "rationale": "restructure search: real added line inside the authored market cap",
    })
  # The candidate's payroll level is LOADED cost (the row basis); the
  # directive's team payroll is compared against STATED wages by the
  # coherence consumption — translate back to the wage basis.
  _bf = max(1.0, min(2.0, float(payroll_burden_factor or 1.0)))
  _team_loaded = float(candidate.get("annual_payroll") or base_levels.get("annual_payroll") or 0.0)
  # The solved COGS shape: with per-line margins, the mature blended
  # ratio of the WINNING mix (computed at Q11) — the real pipeline aims
  # its COGS band at the mix the solver actually designed.
  _solved_cogs = candidate.get("cogs_pct")
  if line_margins and isinstance(base_model_input, dict):
    _blend_rev = _base_line_revenue_series(base_model_input)
    _blend_cogs_row: List[float] = []
    for _row in ((base_model_input.get("sections") or {}).get("expenses") or []):
      if isinstance(_row, dict) and str(_row.get("label") or "").strip() == "Cost of Goods Sold":
        _blend_cogs_row = list(_row.get("values") or [])
        break
    if _blend_cogs_row:
      _b = blended_cogs_ratio(
        base_line_rev=_blend_rev, base_cogs_row=_blend_cogs_row,
        candidate=candidate, line_margins=line_margins, q=11,
      )
      if _b is not None:
        _solved_cogs = round(_b, 6)
  # OUTPUT INVARIANT (landing-fidelity #3): the directive is the shipped
  # artifact — it must satisfy the bounds that authored it. The de-burden
  # quotient is clamped in WAGE basis (the basis team.min/max are
  # authored in); rent and cost floors likewise. With the in-solve
  # moderation clamp these are no-ops; when one fires it is TRACED so a
  # verified-vs-shipped drift can never be silent again.
  _inv_clamps: List[str] = []

  def _inv_apply(value: Optional[float], lo: Optional[float], hi: Optional[float], name: str) -> Optional[float]:
    if value is None:
      return None
    v = float(value)
    lo_f = float(lo) if lo is not None else None
    hi_f = float(hi) if hi is not None else None
    if lo_f is not None and hi_f is not None and hi_f < lo_f:
      hi_f = lo_f
    if lo_f is not None and v < lo_f:
      _inv_clamps.append(f"{name}:{v}-> floor {lo_f}")
      return lo_f
    if hi_f is not None and v > hi_f:
      _inv_clamps.append(f"{name}:{v}-> ceiling {hi_f}")
      return hi_f
    return v

  _team_b = bounds.get("team") or {}
  _team_wages = _inv_apply(
    round(_team_loaded / _bf, 2),
    _team_b.get("min_annual_payroll"), _team_b.get("max_annual_payroll"),
    "team.annual_payroll",
  )
  directive: Dict[str, Any] = {
    "feasible": True,
    "team": {
      "annual_payroll": round(float(_team_wages), 2) if _team_wages is not None else None,
      "structure": str((bounds.get("team") or {}).get("structure_at_min") or "")[:300],
      "rationale": str((bounds.get("team") or {}).get("rationale") or "")[:500],
    },
    # Per-line prices ride revenue_mix.lines; the global pricing lever
    # stays neutral so no line is priced past ITS OWN market ceiling.
    "pricing": {
      "price_multiplier_q11": 1.0,
      "price_multiplier_q20": 1.0,
      "rationale": "restructure search: per-line pricing inside each line's market ceiling",
    },
    "facility": {
      "quarterly_rent_target": _inv_apply(
        float(candidate["quarterly_rent"]) if candidate.get("quarterly_rent") is not None else None,
        (bounds.get("facility") or {}).get("min_quarterly_rent"),
        (bounds.get("facility") or {}).get("max_quarterly_rent"),
        "facility.quarterly_rent_target",
      ),
      "rationale": str((bounds.get("facility") or {}).get("rationale") or "")[:500],
    },
    "growth": {},
    "revenue_mix": {"lines": lines_out, "new_lines": new_lines_out},
    "cost_structure": {
      "cogs_percent_of_revenue": _inv_apply(
        _solved_cogs, (bounds.get("cost_floors") or {}).get("cogs_percent_of_revenue_min"), None,
        "cost_structure.cogs_percent_of_revenue",
      ),
      "marketing_percent_of_revenue": _inv_apply(
        candidate.get("marketing_pct"),
        (bounds.get("cost_floors") or {}).get("marketing_percent_of_revenue_min"), None,
        "cost_structure.marketing_percent_of_revenue",
      ),
      "g_and_a_percent_of_revenue": _inv_apply(
        candidate.get("g_and_a_pct"),
        (bounds.get("cost_floors") or {}).get("g_and_a_percent_of_revenue_min"), None,
        "cost_structure.g_and_a_percent_of_revenue",
      ),
      "rationale": str((bounds.get("cost_floors") or {}).get("rationale") or "")[:500],
    },
    "product_mix_notes": "",
    "overall_rationale": overall_rationale[:900],
    "reality_constraints": dict(bounds.get("reality_constraints") or {}),
    "notes": ["restructure_v2_search"],
  }
  if _inv_clamps:
    directive["invariant_clamps"] = _inv_clamps[:12]
    directive["notes"] = list(directive["notes"]) + ["bounds_invariant_clamped"]
  return directive


__all__ = [
  "apply_candidate",
  "search_viable_configuration",
  "candidate_to_directive",
]
