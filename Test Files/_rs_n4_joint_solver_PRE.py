"""RESTRUCTURE JOINT SOLVE — numeric_solver.solve_review_plan, pointed
at viability.

FIRES ONLY ON NON-VIABLE (the hook gates on the acceptance verdict; a
viable plan never enters). The design, final and simple:

  - GPT (outside the loop) authored the reality bounds per driver and
    the viability target is the acceptance gate's own checkpoints.
  - THE SOLVER — the existing SciPy joint optimizer
    (numeric_solver.solve_review_plan) — moves ALL levers
    simultaneously (per-line price, per-line volume, new-line volume,
    payroll, rent, COGS/marketing/G&A ratios) inside those bounds to
    hit the targets. One joint solve. No rounds, no sweeps, no GPT
    inside the loop.
  - GPT (outside the loop) reviews the solved configuration.

The solved Q11/Q20 point is translated to the restructure directive
(the glide the real pipeline consumes) and the glided trajectory is
verified with the fast evaluator's HONEST scoring (per-line margin
blend included) — if the solver leaned on a cost ratio the mix does
not justify, the verify fails and the targets escalate for one more
solve. The real pipeline still issues the only verdict that counts.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.post_intake_restructure.searcher import (  # type: ignore
  _base_levels,
  _base_line_revenue_series,
  _glide,
  _key,
  apply_candidate,
  line_margins_from_bounds,
  synthesize_new_line_rows,
)
from client_intake_and_finmo.post_intake_restructure.fast_evaluator import (  # type: ignore
  build_fast_finmo,
  score_viability,
)

_SOLVE_DEADLINE_SECONDS = 240.0
_TARGET_QUARTERS = (11, 20)
# Viability targets as margins on the BASE plan's revenue at the target
# quarter; escalation step when the honest verify rejects the solve.
_TARGET_LADDER = (
  {"ni_margin": 0.03, "ebitda_margin": 0.06},
  {"ni_margin": 0.07, "ebitda_margin": 0.11},
)


class RestructureNetDeadError(RuntimeError):
  """FAIL-LOUD (dead-net fix 2026-08-16): the restructure search ended
  with ZERO candidate evaluations because EVERY rung raised the SAME
  exception — a broken net, not an honest exhaustion. Honest exhaustion
  (rungs that solved and verified non-viable, or returned no updates)
  stays quiet; this raises so the failure reaches the run's failure
  surface (run_status / diagnostics / failure email) instead of
  shipping a failed plan silently (Nine Fathom 6d2823db)."""

  def __init__(self, *, violation: str, rungs: int, trace: List[str]) -> None:
    self.violation = str(violation or "")
    self.rungs = int(rungs)
    self.trace = list(trace or [])
    super().__init__(
      f"restructure_net_dead: every rung ({self.rungs}/{self.rungs}) raised the identical "
      f"exception with zero candidate evaluations — {self.violation}"
    )

  def to_dict(self) -> Dict[str, Any]:
    return {
      "failure_stage": "restructure_joint_solve",
      "failure_reason": "restructure_net_dead",
      "violation": self.violation,
      "rungs": self.rungs,
      "trace": list(self.trace),
    }


def _num(value: Any) -> Optional[float]:
  try:
    v = float(value)
    return v if v == v else None
  except (TypeError, ValueError):
    return None


def _prepare_restructure_model(
  base_model_input: Dict[str, Any],
  bounds: Dict[str, Any],
) -> Dict[str, Any]:
  """The solve-ready model: new-line rows synthesized at ZERO volume
  (their Capacity is an adjustable cell), revenue rows writable (the
  restructure is the redesign authority), the payroll row freed from
  its derived-schedule regeneration so it is a real lever."""
  mi = copy.deepcopy(base_model_input)
  for holder_key in ("derived_driver_policies", "derived_driver_runtime"):
    holder = mi.get(holder_key)
    if isinstance(holder, dict):
      holder.pop("expenses::Payroll", None)
  rev_rows = ((mi.get("sections") or {}).get("revenue") or [])
  for row in rev_rows:
    if isinstance(row, dict):
      row["controller_write"] = True
      row["derived_driver"] = None
  # The restructure's adjustable cells include the cost structure — the
  # expense rows ship controller_write=False (owned by their handlers in
  # normal runs) and would silently vanish from the solver's lever map.
  _RESTRUCTURE_EXPENSE_LEVERS = {
    "Payroll", "Lease", "Cost of Goods Sold", "Marketing",
    "General & Administrative",
  }
  for row in ((mi.get("sections") or {}).get("expenses") or []):
    if isinstance(row, dict) and str(row.get("label") or "").strip() in _RESTRUCTURE_EXPENSE_LEVERS:
      row["controller_write"] = True
      row["derived_driver"] = None
  templates: Dict[str, Dict[str, Any]] = {}
  for row in rev_rows:
    if isinstance(row, dict):
      d = str(row.get("driver") or "").strip()
      if d in ("Unit Price", "Capacity", "Utilization") and d not in templates:
        templates[d] = row
  for nl in (bounds.get("new_line_candidates") or []):
    price = float(_num(nl.get("unit_price")) or 0.0)
    rev_max = float(_num(nl.get("q11_quarterly_revenue_max")) or 0.0)
    if price <= 0.0 or rev_max <= 0.0:
      continue
    rows = synthesize_new_line_rows(
      templates, rev_rows,
      lob=str(nl.get("lob") or "New"),
      product=str(nl.get("product") or "New Line"),
      unit_price=price,
      q11_quarterly_revenue=rev_max,
      gross_margin_pct=nl.get("gross_margin_pct"),
    )
    # Adjustable cell semantics: the line EXISTS at a nominal 1% of its
    # market cap (the capacity-shaping policy requires positive
    # structural capacity in every slot); the solver chooses how much
    # of it (0 .. market cap) the design actually uses.
    for row in rows:
      if str(row.get("driver") or "").strip() == "Capacity":
        row["values"] = [round(v * 0.01, 6) for v in (row.get("values") or [])]
    rev_rows.extend(rows)
  return mi


def _lever_plan(
  prepared_model: Dict[str, Any],
  bounds: Dict[str, Any],
  base_levels: Dict[str, Any],
  payroll_burden_factor: float,
) -> Dict[str, Any]:
  """All adjustable cells with their per-quarter bounds:
  {lever_id: {quarter: (lo, hi)}} plus lookup metadata."""
  plan: Dict[str, Any] = {"bounds": {}, "line_of_lever": {}, "new_line_of_lever": {}}
  by_key = {
    f"{_key(l.get('lob'))}/{_key(l.get('product'))}": l
    for l in (bounds.get("existing_lines") or [])
  }
  new_by_key = {
    f"{_key(nl.get('lob'))}/{_key(nl.get('product'))}": nl
    for nl in (bounds.get("new_line_candidates") or [])
  }
  rows = ((prepared_model.get("sections") or {}).get("revenue") or [])
  for row in rows:
    if not isinstance(row, dict):
      continue
    driver = str(row.get("driver") or "").strip()
    lever_id = str(row.get("lever_id") or "").strip()
    if not lever_id or driver not in ("Unit Price", "Capacity"):
      continue
    lk = f"{_key(row.get('lob'))}/{_key(row.get('product'))}"
    spec = by_key.get(lk)
    nl_spec = new_by_key.get(lk)
    values = row.get("values") or []
    per_q: Dict[int, Any] = {}
    for q in _TARGET_QUARTERS:
      base_q = float(_num(values[q] if q < len(values) else None) or 0.0)
      if nl_spec is not None:
        if driver == "Capacity":
          price = float(_num(nl_spec.get("unit_price")) or 1.0)
          cap_max = float(_num(nl_spec.get("q11_quarterly_revenue_max")) or 0.0) / max(1e-9, price)
          per_q[q] = (0.0, cap_max)
        else:
          continue  # new-line price is the authored price, not a lever
      elif spec is not None:
        if driver == "Unit Price":
          pmax = float(_num(spec.get("price_multiplier_max")) or 1.0)
          per_q[q] = (base_q, base_q * max(1.0, pmax))
        else:
          vmax = float(_num(spec.get("volume_multiplier_max")) or 1.0)
          lo = 0.0 if bool(spec.get("can_drop")) else base_q * 0.5
          per_q[q] = (lo, base_q * max(1.0, vmax))
      else:
        continue
    if per_q:
      plan["bounds"][lever_id] = per_q
      if nl_spec is not None:
        plan["new_line_of_lever"][lever_id] = lk
      else:
        plan["line_of_lever"][lever_id] = lk
  team = bounds.get("team") or {}
  bf = max(1.0, min(2.0, float(payroll_burden_factor or 1.0)))
  team_lo = float(_num(team.get("min_annual_payroll")) or 0.0) * bf / 4.0
  team_hi = max(team_lo, float(_num(team.get("max_annual_payroll")) or 0.0) * bf / 4.0,
                float(base_levels.get("annual_payroll") or 0.0) / 4.0)
  fac = bounds.get("facility") or {}
  rent_lo = float(_num(fac.get("min_quarterly_rent")) or 0.0)
  rent_hi = max(rent_lo, float(_num(fac.get("max_quarterly_rent")) or rent_lo),
                float(base_levels.get("quarterly_rent") or 0.0))
  floors = bounds.get("cost_floors") or {}
  ratio_bounds = {
    "expenses::Cost of Goods Sold": (
      float(_num(floors.get("cogs_percent_of_revenue_min")) or 0.01),
      max(float(_num(floors.get("cogs_percent_of_revenue_min")) or 0.01),
          float(base_levels.get("cogs_pct") or 0.0)),
    ),
    "expenses::Marketing": (
      float(_num(floors.get("marketing_percent_of_revenue_min")) or 0.005),
      max(float(_num(floors.get("marketing_percent_of_revenue_min")) or 0.005),
          float(base_levels.get("marketing_pct") or 0.0)),
    ),
    "expenses::General & Administrative": (
      float(_num(floors.get("g_and_a_percent_of_revenue_min")) or 0.005),
      max(float(_num(floors.get("g_and_a_percent_of_revenue_min")) or 0.005),
          float(base_levels.get("g_and_a_pct") or 0.0)),
    ),
  }
  for q in _TARGET_QUARTERS:
    plan["bounds"].setdefault("expenses::Payroll", {})[q] = (team_lo, team_hi)
    plan["bounds"].setdefault("expenses::Lease", {})[q] = (rent_lo, rent_hi)
    for lever_id, (lo, hi) in ratio_bounds.items():
      plan["bounds"].setdefault(lever_id, {})[q] = (lo, hi)
  return plan


def _base_quarter_revenue(prepared_model: Dict[str, Any], q: int) -> float:
  total = 0.0
  for series in _base_line_revenue_series(prepared_model).values():
    total += series[q] if q < len(series) else 0.0
  return total


def run_restructure_joint_solve(
  *,
  base_model_input: Dict[str, Any],
  bounds: Dict[str, Any],
  business_naics_6: Optional[str] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
) -> Dict[str, Any]:
  """ONE joint solve (with bounded target escalation on honest-verify
  rejection). Returns {found, candidate, score, trace, ...} in the same
  shape the hook consumes."""
  from client_intake_and_finmo.numeric_solver import solve_review_plan  # type: ignore

  base_lv = _base_levels(base_model_input)
  line_margins = line_margins_from_bounds(bounds)
  stated_wages = float(_num((financials_json or {}).get("payroll_total_year1")) or 0.0)
  payroll_burden_factor = (
    (float(base_lv.get("annual_payroll") or 0.0) / stated_wages)
    if stated_wages > 0 and float(base_lv.get("annual_payroll") or 0.0) > 0 else 1.0
  )
  prepared = _prepare_restructure_model(base_model_input, bounds)
  plan = _lever_plan(prepared, bounds, base_lv, payroll_burden_factor)

  # IMPACT ORDER — the solver's deterministic seed budget covers the
  # first dimensions first: revenue-side levers (where restructures
  # live) ahead of the cost rows, never alphabetical.
  def _lever_rank(lever_id: str) -> tuple:
    if lever_id in plan["new_line_of_lever"]:
      return (0, lever_id)
    if lever_id.endswith("::Unit Price"):
      return (1, lever_id)
    if lever_id.startswith("revenue::"):
      return (2, lever_id)
    if lever_id == "expenses::Payroll":
      return (3, lever_id)
    if lever_id == "expenses::Lease":
      return (4, lever_id)
    return (5, lever_id)

  lever_ids = sorted(plan["bounds"].keys(), key=_lever_rank)
  trace: List[str] = [f"joint_solve levers={len(lever_ids)}"]

  result: Dict[str, Any] = {
    "found": False, "candidate": {}, "score": {}, "trace": trace,
    "base_levels": base_lv, "line_margins": line_margins,
    "payroll_burden_factor": payroll_burden_factor,
    "candidate_first_viable": None, "landed_first_viable": None,
    "evals": 0,
  }

  # ONE MARGIN AUTHORITY — when the executive's margin-band judgment is
  # stamped, its floor IS the solve's EBITDA target floor (glided
  # Q11->Q20 by the band's own accessor). The ladder default is only
  # the fallback seed for businesses with no stamped band.
  try:
    from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (  # type: ignore  # noqa: E501
      judged_ebitda_floor_for_quarter,
      margin_band_from_model_input,
    )
    _judged_band = margin_band_from_model_input(base_model_input)
  except Exception:  # noqa: BLE001 — fallback default stands
    _judged_band = None
    judged_ebitda_floor_for_quarter = None  # type: ignore[assignment]

  # Dead-net detection: one signature per rung that RAISED (an
  # exception, not a no-update return); a rung that ran and produced
  # updates records nothing here.
  rung_raise_signatures: List[str] = []
  rungs_attempted = 0

  for ladder_ix, rung in enumerate(_TARGET_LADDER, start=1):
    rungs_attempted += 1
    targets = []
    for q in _TARGET_QUARTERS:
      rev_q = _base_quarter_revenue(prepared, q)
      eb_floor = float(rung["ebitda_margin"])
      if _judged_band is not None and judged_ebitda_floor_for_quarter is not None:
        _jf = judged_ebitda_floor_for_quarter(_judged_band, q)
        if _jf is not None:
          eb_floor = max(eb_floor, float(_jf))
          if ladder_ix == 1 and q == _TARGET_QUARTERS[0]:
            trace.append(f"ebitda floor governed by executive band: q11 {round(float(_jf), 4)}")
      # BELIEVABILITY CEILING (fragility-class Wave 1): the ladder never
      # ASKS for more than the executive's judged band target — the
      # solve aims inside the band the executive itself judges
      # believable, not past it. (Escalation rungs above the target are
      # clamped; the floor still governs from below.)
      if _judged_band is not None:
        _q_key = "q11" if q <= 11 else "q20"
        _jt = ((_judged_band.get(_q_key) or {}).get("target"))
        if _jt is not None and eb_floor > float(_jt):
          eb_floor = max(float(_jt), 0.0)
          if q == _TARGET_QUARTERS[0]:
            trace.append(
              f"ebitda target clamped to judged band target: {_q_key} {round(float(_jt), 4)}"
            )
      # CW-021 NI-demote (mirrors the compliant EBITDA half): the judged
      # ni_margin_floor_q11 governs the NI target when stamped — max()
      # keeps the rung constant as the floor-of-floors, so a judged
      # floor above 0.03 makes the rescue STRICTER (70/74 real stamps)
      # and a judged floor below it never thins the rescue under the
      # rung. Constants remain the judgment-absent seeds.
      ni_floor = float(rung["ni_margin"])
      if _judged_band is not None:
        _jni = _judged_band.get("ni_margin_floor_q11")
        if _jni is not None:
          _new_floor = max(ni_floor, float(_jni))
          if _new_floor > ni_floor and ladder_ix == 1 and q == _TARGET_QUARTERS[0]:
            trace.append(
              f"ni floor governed by executive judgment: {round(float(_jni), 4)}"
            )
          ni_floor = _new_floor
      targets.append({
        "quarter_index": q,
        "net_income": round(rev_q * ni_floor, 2),
        "ebitda": round(rev_q * eb_floor, 2),
      })
    # Guidance anchors: seed the solve at each lever's NI-FAVORABLE
    # bound (price at the market ceiling, costs at their physics
    # floors, new lines at their market caps, existing volumes held).
    # The anchor is a STARTING POINT for the joint refinement — the
    # bounds stay the fence, the honest verify and the executive's
    # review stay the judges.
    rows_by_lever = {
      str(r.get("lever_id") or "").strip(): r
      for r in ((prepared.get("sections") or {}).get("revenue") or [])
      if isinstance(r, dict)
    }
    translated_updates: List[Dict[str, Any]] = []
    for lever_id in lever_ids:
      for q in _TARGET_QUARTERS:
        b = plan["bounds"].get(lever_id, {}).get(q)
        if not b:
          continue
        lo, hi = float(b[0]), float(b[1])
        r = rows_by_lever.get(lever_id) or {}
        vals = r.get("values") or []
        base_q = float(_num(vals[q] if q < len(vals) else None) or 0.0)
        if lever_id in plan["new_line_of_lever"]:
          favorable = hi
        elif lever_id.endswith("::Unit Price"):
          favorable = hi
        elif lever_id.startswith("revenue::"):
          favorable = base_q  # existing volume: anchor at stated
        else:
          favorable = lo  # costs anchor at their floors
        translated_updates.append({
          "lever_id": lever_id,
          "quarter_index": q,
          "exact_value": round(float(favorable), 6),
          "baseline_value": round(base_q, 6),
        })
    review_plan = {
      "contract_version": "review_plan_restructure_viability_v1",
      "decision_source": "restructure_stage",
      "translated_action_packages": [{
        "action_id": f"restructure_viability_r{ladder_ix}",
        "solver_allowed_lever_ids": list(lever_ids),
        "required_target_metric_keys": ["net_income", "ebitda"],
        "quarter_target_metrics": targets,
        "translated_updates": translated_updates,
      }],
    }
    contract = {
      "contract_version": "numeric_solver_contract_restructure_v1",
      "pass_name": "restructure_viability",
      "runtime_deadline_monotonic": time.monotonic() + _SOLVE_DEADLINE_SECONDS,
      "decision_source": "restructure_stage",
      "solver_settings": {"aggressiveness": "structural"},
      "issue_target_packets": [{
        "issue_code": "restructure_viability",
        "repair_targets": [
          {
            "quarter": q,
            "driver_paths": [
              {
                "lever": lever_id,
                "suggested_min_value": float(plan["bounds"][lever_id][q][0]),
                "suggested_max_value": float(plan["bounds"][lever_id][q][1]),
              }
              for lever_id in lever_ids
              if q in plan["bounds"].get(lever_id, {})
            ],
          }
          for q in _TARGET_QUARTERS
        ],
      }],
    }
    try:
      solve = solve_review_plan(
        model_input_json=copy.deepcopy(prepared),
        review_plan=review_plan,
        numeric_solver_contract=contract,
        fallback_exact_updates=[],
      )
    except Exception as exc:  # noqa: BLE001 — a crashed rung fails; ALL rungs crashing identically raises below
      trace.append(f"rung {ladder_ix}: solve_raised {type(exc).__name__}: {str(exc)[:160]}")
      rung_raise_signatures.append(f"{type(exc).__name__}: {str(exc)[:400]}")
      continue
    exact_updates = solve.get("exact_updates") or []
    trace.append(
      f"rung {ladder_ix}: state={solve.get('execution_state')} updates={len(exact_updates)}"
    )
    if not exact_updates:
      continue

    solved: Dict[Any, float] = {}
    for item in exact_updates:
      if isinstance(item, dict):
        solved[(str(item.get("lever_id") or "").strip(), int(_num(item.get("quarter_index")) or 0))] = float(
          _num(item.get("exact_value")) or 0.0
        )
    trace.append(
      "rung %s solved_q11: %s" % (
        ladder_ix,
        {k[0].split("::")[-1] + "/" + k[0].split("::")[1][:12]: round(v, 2) for k, v in solved.items() if k[1] == 11},
      )
    )

    # Translate the solved Q11/Q20 point into the directive candidate
    # (the glide the real pipeline consumes).
    candidate: Dict[str, Any] = {}
    _sections = prepared.get("sections") or {}
    row_by_lever = {
      str(r.get("lever_id") or "").strip(): r
      for section in ("revenue", "expenses")
      for r in (_sections.get(section) or [])
      if isinstance(r, dict) and str(r.get("lever_id") or "").strip()
    }

    def _baseline_at(lever_id: str, q: int) -> Optional[float]:
      r = row_by_lever.get(lever_id) or {}
      vals = r.get("values") or []
      return _num(vals[q] if q < len(vals) else None)

    def _moved(lever_id: str, q: int, *, rel: float = 0.005, absolute: float = 0.002) -> Optional[float]:
      """The solved value ONLY when the solver actually moved this cell
      — an untouched cell must keep its base trajectory, not become a
      level target (gliding a row's natural ramp value backward through
      earlier quarters corrupts the plan)."""
      val = solved.get((lever_id, q))
      base_q = _baseline_at(lever_id, q)
      if val is None or base_q is None:
        return None
      if abs(val - base_q) <= max(abs(base_q) * rel, absolute):
        return None
      return val

    def _mult(lever_id: str, q: int) -> Optional[float]:
      val = _moved(lever_id, q)
      base_q = _baseline_at(lever_id, q)
      if val is None or base_q is None or base_q <= 0:
        return None
      return val / base_q

    for lever_id, lk in plan["line_of_lever"].items():
      driver = "price" if lever_id.endswith("::Unit Price") else "volume"
      m11 = _mult(lever_id, 11)
      m20 = _mult(lever_id, 20)
      if m11 is None and m20 is None:
        continue
      cfg = candidate.setdefault("lines", {}).setdefault(lk, {})
      cfg[f"{driver}_m11"] = round(m11 if m11 is not None else (m20 or 1.0), 4)
      cfg[f"{driver}_m20"] = round(m20 if m20 is not None else (m11 or 1.0), 4)
    new_by_key = {
      f"{_key(nl.get('lob'))}/{_key(nl.get('product'))}": nl
      for nl in (bounds.get("new_line_candidates") or [])
    }
    for lever_id, lk in plan["new_line_of_lever"].items():
      cap11 = solved.get((lever_id, 11))
      spec = new_by_key.get(lk) or {}
      price = float(_num(spec.get("unit_price")) or 0.0)
      if cap11 is None or price <= 0.0 or cap11 * price < 500.0:
        continue
      candidate.setdefault("new_lines", []).append({
        "lob": spec.get("lob"), "product": spec.get("product"),
        "unit_price": price,
        "gross_margin_pct": spec.get("gross_margin_pct"),
        "q11_quarterly_revenue": round(cap11 * price, 2),
      })
    pay_q11 = _moved("expenses::Payroll", 11, rel=0.01, absolute=50.0)
    if pay_q11 is not None:
      # The solver's payroll is the loaded cost AT the solved volume;
      # the candidate's payroll lever is the team at TODAY'S volume
      # (labor coupling re-scales it) — divide the coupling back out.
      lines_cfg = candidate.get("lines") or {}
      base_rev_series = _base_line_revenue_series(base_model_input)
      total = 0.0
      scaled = 0.0
      for lk, series in base_rev_series.items():
        rev_q = series[11] if len(series) > 11 else 0.0
        total += rev_q
        cfg = lines_cfg.get(lk) or {}
        v11 = float(cfg.get("volume_m11") if cfg.get("volume_m11") is not None else 1.0)
        scaled += rev_q * v11
      labor_mult_q11 = (scaled / total) if total > 0 else 1.0
      candidate["annual_payroll"] = round(pay_q11 * 4.0 / max(1e-9, labor_mult_q11), 2)
    rent_q11 = _moved("expenses::Lease", 11, rel=0.01, absolute=50.0)
    if rent_q11 is not None:
      candidate["quarterly_rent"] = round(rent_q11, 2)
    for lever_id, field in (
      ("expenses::Cost of Goods Sold", "cogs_pct"),
      ("expenses::Marketing", "marketing_pct"),
      ("expenses::General & Administrative", "g_and_a_pct"),
    ):
      v = _moved(lever_id, 11)
      if v is not None:
        candidate[field] = round(v, 6)
    if line_margins:
      candidate.pop("cogs_pct", None)  # the mix owns COGS in the honest verify

    # BELIEVABILITY MODERATION (fragility-class Wave 1): the solver's
    # favorable-corner seed can overshoot the executive's judged band
    # HIGH ("above this the forecast stops being believable") even with
    # clamped targets, because floor targets exert no downward pull.
    # Walk the WHOLE design back toward as-stated (deterministic
    # bisection on one moderation factor t: candidate levers scaled
    # base + t*(solved - base)) until the landed Q11 EBITDA margin sits
    # at or below the judged high. If no moderated design stays viable,
    # the unmoderated candidate proceeds to the verify and fails
    # honestly. Judgment absent -> no ceiling (today's behavior).
    def _scale_candidate(cand: Dict[str, Any], t: float) -> Dict[str, Any]:
      out = copy.deepcopy(cand)
      for cfg in (out.get("lines") or {}).values():
        for k in ("price_m11", "price_m20", "volume_m11", "volume_m20"):
          if cfg.get(k) is not None:
            cfg[k] = round(1.0 + t * (float(cfg[k]) - 1.0), 4)
      for nl in (out.get("new_lines") or []):
        if nl.get("q11_quarterly_revenue") is not None:
          nl["q11_quarterly_revenue"] = round(t * float(nl["q11_quarterly_revenue"]), 2)
      for key, base_val in (
        ("annual_payroll", base_lv.get("annual_payroll")),
        ("quarterly_rent", base_lv.get("quarterly_rent")),
        ("marketing_pct", base_lv.get("marketing_pct")),
        ("g_and_a_pct", base_lv.get("g_and_a_pct")),
        ("cogs_pct", base_lv.get("cogs_pct")),
      ):
        if out.get(key) is not None and base_val is not None:
          out[key] = round(float(base_val) + t * (float(out[key]) - float(base_val)), 6)
      # OUTPUT INVARIANT (landing-fidelity #3): the blend target is the
      # as-stated base, which can itself sit OUTSIDE the executive's
      # authored bounds (Redux: base loaded payroll below the loaded
      # team floor) — so moderation could emit a design the executive's
      # own judgment calls unbelievable. Re-clamp every scalar into its
      # authored bounds HERE, inside the solve, so the candidate we
      # verify is the candidate we ship.
      _inv_bounds = plan.get("bounds") or {}

      def _inv_clamp(value: float, lo: float, hi: float) -> float:
        return min(max(value, lo), max(lo, hi))

      _inv_team = (_inv_bounds.get("expenses::Payroll") or {}).get(11)
      if _inv_team and out.get("annual_payroll") is not None:
        out["annual_payroll"] = round(
          _inv_clamp(float(out["annual_payroll"]), float(_inv_team[0]) * 4.0, float(_inv_team[1]) * 4.0), 2)
      _inv_rent = (_inv_bounds.get("expenses::Lease") or {}).get(11)
      if _inv_rent and out.get("quarterly_rent") is not None:
        out["quarterly_rent"] = round(
          _inv_clamp(float(out["quarterly_rent"]), float(_inv_rent[0]), float(_inv_rent[1])), 2)
      for _inv_lever, _inv_field in (
        ("expenses::Cost of Goods Sold", "cogs_pct"),
        ("expenses::Marketing", "marketing_pct"),
        ("expenses::General & Administrative", "g_and_a_pct"),
      ):
        _inv_rb = (_inv_bounds.get(_inv_lever) or {}).get(11)
        if _inv_rb and out.get(_inv_field) is not None:
          out[_inv_field] = round(
            _inv_clamp(float(out[_inv_field]), float(_inv_rb[0]), float(_inv_rb[1])), 6)
      return out

    def _landed_q11_eb(cand: Dict[str, Any]) -> Optional[float]:
      try:
        mi_t = apply_candidate(base_model_input, cand, line_margins=line_margins or None)
        fm_t = build_fast_finmo(mi_t)
        rows_t = {
          int(float(r.get("quarter_index"))): r
          for r in fm_t.get("quarter_rows") or [] if isinstance(r, dict)
        }
        r11 = rows_t.get(11) or {}
        rev = float(r11.get("revenue") or 0.0)
        if rev <= 0:
          return None
        return float(r11.get("ebitda") or 0.0) / rev
      except Exception:  # noqa: BLE001
        return None

    _judged_high = None
    if _judged_band is not None:
      _judged_high = ((_judged_band.get("q11") or {}).get("high"))
    if _judged_high is not None:
      _eb_full = _landed_q11_eb(candidate)
      result["evals"] = int(result.get("evals") or 0) + 1
      if _eb_full is not None and _eb_full > float(_judged_high) + 0.01:
        lo_t, hi_t = 0.0, 1.0
        best_t = None
        for _ in range(6):
          mid = (lo_t + hi_t) / 2.0
          _eb_mid = _landed_q11_eb(_scale_candidate(candidate, mid))
          result["evals"] = int(result.get("evals") or 0) + 1
          if _eb_mid is not None and _eb_mid <= float(_judged_high) + 0.01:
            best_t = mid
            lo_t = mid
          else:
            hi_t = mid
        if best_t is not None:
          moderated = _scale_candidate(candidate, best_t)
          trace.append(
            f"rung {ladder_ix}: moderated to judged band high "
            f"(t={round(best_t, 3)}, q11 eb {round(_eb_full, 4)} -> <= {round(float(_judged_high), 4)})"
          )
          candidate = moderated

    # HONEST VERIFY — glide the solved point and score the full
    # trajectory with the gate's own checks + per-line margin blend
    # (apply_candidate synthesizes the chosen new lines and frees the
    # payroll row itself; the raw base keeps Q1 stated reality).
    mi_glided = apply_candidate(base_model_input, candidate, line_margins=line_margins or None)
    try:
      finmo = build_fast_finmo(mi_glided)
      score = score_viability(
        model_input_json=mi_glided, finmo_json=finmo,
        business_naics_6=business_naics_6, ops_json=ops_json,
        financials_json=financials_json, planning_mode=planning_mode,
      )
      score.pop("finmo_json", None)
    except Exception as exc:  # noqa: BLE001
      score = {"viable_pnl": False, "failed_binding": [f"verify_error:{type(exc).__name__}"], "landed": {}}
    result["evals"] = int(result.get("evals") or 0) + 1
    trace.append(
      f"rung {ladder_ix}: verify viable={score.get('viable_pnl')} failed={score.get('failed_binding')}"
    )
    _prev_failed = len((result.get("score") or {}).get("failed_binding") or [99] * 9)
    if not result.get("candidate") or len(score.get("failed_binding") or []) < _prev_failed:
      # Keep the BEST rung's design (fewest failing checks), never
      # just the last one.
      result["candidate"] = candidate
      result["score"] = score
    if score.get("viable_pnl"):
      # The restructure ships the REVIEWER-APPROVED design — the
      # growing, diversified business. Line justification belongs to
      # the reviewer (it interrogates each line's deliverability and
      # sizes the ramps); pruning to bare viability optimizes for
      # minimum-viable, trades growth for a flatline, and a flat plan
      # is LESS fundable, not more.
      result["candidate"] = candidate
      result["score"] = score
      result["found"] = True
      result["candidate_first_viable"] = copy.deepcopy(candidate)
      result["landed_first_viable"] = copy.deepcopy(score.get("landed"))
      break

  result["trace"] = trace
  # FAIL LOUD ON A DEAD SEARCH: zero evaluations AND every rung raised
  # AND one identical signature = a structurally broken net (the
  # Nine Fathom shape: an identical ContractViolation on every rung).
  # Distinct from honest exhaustion — rungs that solved (evals>0), or
  # returned no updates, or raised DIFFERENT errors — which stays quiet.
  if (
    not result.get("found")
    and int(result.get("evals") or 0) == 0
    and rungs_attempted > 0
    and len(rung_raise_signatures) == rungs_attempted
    and len(set(rung_raise_signatures)) == 1
  ):
    trace.append(
      f"dead_net: {rungs_attempted}/{rungs_attempted} rungs raised the identical exception, evals=0 — raising"
    )
    raise RestructureNetDeadError(
      violation=rung_raise_signatures[0], rungs=rungs_attempted, trace=trace,
    )
  if not result.get("found") and int(result.get("evals") or 0) == 0 and rung_raise_signatures:
    trace.append(
      f"dead_search_mixed: {len(rung_raise_signatures)}/{rungs_attempted} rungs raised "
      f"({len(set(rung_raise_signatures))} distinct), evals=0"
    )
  return result


__all__ = ["RestructureNetDeadError", "run_restructure_joint_solve"]
