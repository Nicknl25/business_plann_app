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

  for ladder_ix, rung in enumerate(_TARGET_LADDER, start=1):
    targets = []
    for q in _TARGET_QUARTERS:
      rev_q = _base_quarter_revenue(prepared, q)
      targets.append({
        "quarter_index": q,
        "net_income": round(rev_q * float(rung["ni_margin"]), 2),
        "ebitda": round(rev_q * float(rung["ebitda_margin"]), 2),
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
    except Exception as exc:  # noqa: BLE001 — a crashed rung just fails
      trace.append(f"rung {ladder_ix}: solve_raised {type(exc).__name__}: {str(exc)[:160]}")
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
      result["candidate"] = candidate
      result["score"] = score
      result["found"] = True
      result["candidate_first_viable"] = copy.deepcopy(candidate)
      result["landed_first_viable"] = copy.deepcopy(score.get("landed"))
      break

  result["trace"] = trace
  return result


__all__ = ["run_restructure_joint_solve"]
