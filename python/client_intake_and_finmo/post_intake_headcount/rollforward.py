"""PAYROLL AS AN FTE ROLL-FORWARD, BY POSITION GROUP, BY QUARTER.

Nick 2026-09-26, after the Command Investigations model: "design payroll
around this, however the executive deals with it", "the layout needs to look
exactly like this", "the user needs to be able to adjust her forecast for the
FTE just like this one", "stub should be initial numbers", "there should be
groups where possible, not one per person", "the name of the groups would
obviously be tailored to the client's business", "ours needs to be quarters
of course, not months".

WHY THIS EXISTS. Every payroll defect traced on 2026-09-25/26 came from one
choice: the app authored a `target_payroll_percent_of_revenue` and then built
a roster to hit it. Bellweather's executive designed a 431,000 team and proved
Q11 net margin +7.0%; the GPT author chose 62% instead and the built model
carried her stated 482,000 x load, so acceptance failed a plan the app had
already solved. Under a roll-forward that input does not exist: payroll is
FTE x salary and the percentage is an OUTPUT.

It also settles the doctrine problem. Nick retired FTE right-sizing on
2026-08-28 - "payroll is NOT clipped to fit revenue", and shrinking a person
to make payroll fit revenue is exactly that. Here nobody is shrunk: a person
either stays at 1.0 or the plan records an EXIT, which is a decision a real
operator makes and can explain.

THE BLOCK, one per group, identical every time (the client sees these words):

    Opening FTE                 = prior quarter's Ending FTE
    Planned hires               <- HERS to set, forecast quarters only
    Planned exits               <- HERS to set, forecast quarters only
    Ending FTE                  = max(0, opening + hires - exits)
    Average paid FTE            = (opening + ending) / 2
    Average annual salary       = raised once per plan year
    Cash compensation           = average paid FTE x average salary / 4
    Payroll taxes and benefits  = cash compensation x burden rate
    Total employment cost       = cash compensation + taxes and benefits

THE STUB carries her opening reality: the team she has today, at today's pay.
Q1 opens from it, so the stated-payroll reconciliation is true by construction
rather than by a 0.70-1.30 tolerance.

THE THREE IDENTITIES, every group, every quarter (identities(), and the app
checks them rather than trusting them):

    1. ending == opening + hires - exits          (or 0 where that is negative)
    2. opening[q] == ending[q-1]                  (Q1 opens from the stub)
    3. average_paid == (opening + ending) / 2
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence

# The row labels are part of the contract: the workbook renders these words,
# and the client reads them.
ROW_OPENING = "Opening FTE"
ROW_HIRES = "Planned hires"
ROW_EXITS = "Planned exits"
ROW_ENDING = "Ending FTE"
ROW_AVG_FTE = "Average paid FTE"
ROW_AVG_SALARY = "Average annual salary"
ROW_CASH_COMP = "Cash compensation"
ROW_TAXES = "Payroll taxes and benefits"
ROW_TOTAL = "Total employment cost"

BLOCK_ROWS: Sequence[str] = (
  ROW_OPENING, ROW_HIRES, ROW_EXITS, ROW_ENDING, ROW_AVG_FTE,
  ROW_AVG_SALARY, ROW_CASH_COMP, ROW_TAXES, ROW_TOTAL,
)

# The rows she may edit in a forecast quarter. Everything else is derived, so
# the workbook shades exactly these and the app accepts edits only here.
CLIENT_EDITABLE_ROWS: Sequence[str] = (ROW_HIRES, ROW_EXITS)

QUARTERS_PER_YEAR = 4


def _num(value: Any) -> Optional[float]:
  try:
    if value is None or isinstance(value, bool):
      return None
    out = float(value)
    return out if out == out else None
  except (TypeError, ValueError):
    return None


def _f(value: Any, default: float = 0.0) -> float:
  got = _num(value)
  return default if got is None else got


def build_group_rollforward(
  *,
  groups: Sequence[Dict[str, Any]],
  horizon_quarters: int = 20,
  burden_rate: float = 0.22,
  annual_salary_increase: float = 0.03,
  raise_quarter_in_year: int = 1,
) -> Dict[str, Any]:
  """The whole headcount grid, from her opening team forward.

  `groups` is one dict per position group:

      {"group_name": "Studio artisans",     # HER words, never a fixed list
       "opening_fte": 5.0,                  # the stub: what she has today
       "average_annual_salary": 62000.0,    # today's pay for that group
       "is_owner": False,                   # owner groups never carry exits
       "planned_hires": {"3": 1},           # quarter index -> people
       "planned_exits": {"2": 2}}

  Hires and exits are HERS (or the executive's, on a restructure); every
  other row is derived. A raise lands once per plan year, at
  `raise_quarter_in_year`, so a five-year plan compounds four times, not
  twenty.
  """
  horizon = max(1, int(horizon_quarters or 0))
  burden = max(0.0, _f(burden_rate, 0.22))
  raise_rate = _f(annual_salary_increase, 0.03)
  raise_q = max(1, min(QUARTERS_PER_YEAR, int(raise_quarter_in_year or 1)))

  out_groups: List[Dict[str, Any]] = []
  for spec in (groups or []):
    if not isinstance(spec, dict):
      continue
    name = str(spec.get("group_name") or "").strip()
    if not name:
      continue
    is_owner = bool(spec.get("is_owner"))
    opening_stub = max(0.0, _f(spec.get("opening_fte")))
    salary = max(0.0, _f(spec.get("average_annual_salary")))
    hires_by_q = {int(k): _f(v) for k, v in (spec.get("planned_hires") or {}).items()}
    exits_by_q = {int(k): _f(v) for k, v in (spec.get("planned_exits") or {}).items()}

    quarters: List[Dict[str, Any]] = []
    opening = opening_stub
    current_salary = salary
    for q in range(1, horizon + 1):
      # the raise lands once a plan year, never every quarter
      if q > 1 and ((q - 1) % QUARTERS_PER_YEAR) == (raise_q - 1):
        current_salary = round(current_salary * (1.0 + raise_rate), 2)

      hires = max(0.0, hires_by_q.get(q, 0.0))
      # THE OWNER IS NEVER CUT. Not by a title-token exemption downstream -
      # the group simply cannot carry an exit, so it is unrepresentable.
      exits = 0.0 if is_owner else max(0.0, exits_by_q.get(q, 0.0))
      ending = max(0.0, opening + hires - exits)
      avg_fte = (opening + ending) / 2.0
      cash_comp = avg_fte * current_salary / float(QUARTERS_PER_YEAR)
      taxes = cash_comp * burden
      quarters.append({
        "quarter_index": q,
        ROW_OPENING: round(opening, 4),
        ROW_HIRES: round(hires, 4),
        ROW_EXITS: round(exits, 4),
        ROW_ENDING: round(ending, 4),
        ROW_AVG_FTE: round(avg_fte, 4),
        ROW_AVG_SALARY: round(current_salary, 2),
        ROW_CASH_COMP: round(cash_comp, 2),
        ROW_TAXES: round(taxes, 2),
        ROW_TOTAL: round(cash_comp + taxes, 2),
        "client_editable": list(CLIENT_EDITABLE_ROWS),
      })
      opening = ending

    out_groups.append({
      "group_name": name,
      "is_owner": is_owner,
      "stub": {
        ROW_ENDING: round(opening_stub, 4),
        ROW_AVG_SALARY: round(salary, 2),
        "note": "her opening team, at today's pay",
      },
      "quarters": quarters,
    })

  totals = []
  for q in range(1, horizon + 1):
    tot_cash = tot_tax = tot_fte = tot_total = 0.0
    for g in out_groups:
      row = g["quarters"][q - 1]
      tot_cash += _f(row[ROW_CASH_COMP])
      tot_tax += _f(row[ROW_TAXES])
      tot_fte += _f(row[ROW_ENDING])
      # THE TOTAL IS THE SUM OF THE GROUP TOTALS, TO THE CENT. Summing the
      # unrounded parts and rounding once left the income statement a penny
      # away from the group blocks, and "income-statement payroll == sum of
      # group totals" is an identity the app checks, not an approximation.
      tot_total += _f(row[ROW_TOTAL])
    totals.append({
      "quarter_index": q,
      "ending_fte": round(tot_fte, 4),
      ROW_CASH_COMP: round(tot_cash, 2),
      ROW_TAXES: round(tot_tax, 2),
      ROW_TOTAL: round(tot_total, 2),
    })

  return {
    "contract_version": "payroll_fte_rollforward_v1",
    "cadence": "quarterly",
    "horizon_quarters": horizon,
    # THE ASSUMPTIONS ARE LIVE CELLS, NOT BAKED NUMBERS (Nick 2026-09-26:
    # "payroll taxes and benefits need to be an assumption in the wb that
    # can be changed so we can reflect it"). The workbook writes these to
    # the Assumptions sheet and every Payroll-taxes row is a FORMULA
    # pointing at the burden cell - change the cell and the plan recalculates,
    # the way Assumptions!$D$13 drives the reference model. Same for the
    # salary increase. `value` is what the app computed with; `editable`
    # says the client may move it in the sheet.
    "assumptions": {
      "payroll_tax_and_benefit_burden": {
        "value": round(burden, 4),
        "label": "Payroll tax and benefit burden",
        "format": "percent",
        "editable": True,
        "drives_rows": [ROW_TAXES],
      },
      "annual_salary_increase": {
        "value": round(raise_rate, 4),
        "label": "Annual salary increase",
        "format": "percent",
        "editable": True,
        "drives_rows": [ROW_AVG_SALARY],
      },
      "raise_quarter_in_year": {
        "value": raise_q,
        "label": "Quarter the raise lands",
        "format": "integer",
        "editable": True,
        "drives_rows": [ROW_AVG_SALARY],
      },
    },
    # what the workbook must emit as a formula rather than a constant, so a
    # changed assumption flows through the sheet the way it flows through
    # the app.
    "workbook_formula_rows": {
      ROW_TAXES: "{cash_compensation_cell}*{payroll_tax_and_benefit_burden}",
      ROW_AVG_FTE: "AVERAGE({opening_cell},{ending_cell})",
      ROW_ENDING: "MAX(0,{opening_cell}+{hires_cell}-{exits_cell})",
      ROW_CASH_COMP: "{avg_paid_fte_cell}*{avg_salary_cell}/4",
      # The raise is a live cell too (Nick 2026-09-26): the salary row is a
      # formula that carries the prior quarter forward and applies the
      # increase once a plan year, at the raise quarter - so moving the
      # assumption from 3% moves every later salary, and the plan with it.
      # The reference model does the same with IF(MONTH=1, prior*(1+rate)).
      ROW_AVG_SALARY: ("IF({is_raise_quarter},{prior_salary_cell}*"
                       "(1+{annual_salary_increase}),{prior_salary_cell})"),
      ROW_TOTAL: "SUM({cash_compensation_cell}:{taxes_cell})",
    },
    "block_rows": list(BLOCK_ROWS),
    "client_editable_rows": list(CLIENT_EDITABLE_ROWS),
    "groups": out_groups,
    "totals": totals,
  }


def identities(grid: Dict[str, Any]) -> List[str]:
  """Every identity that must hold, checked rather than trusted.

  Returns a list of human-readable breaks; empty means the grid is sound.
  """
  breaks: List[str] = []
  for g in (grid or {}).get("groups") or []:
    name = g.get("group_name")
    prev_ending = _f((g.get("stub") or {}).get(ROW_ENDING))
    for row in g.get("quarters") or []:
      q = row.get("quarter_index")
      opening = _f(row.get(ROW_OPENING))
      hires = _f(row.get(ROW_HIRES))
      exits = _f(row.get(ROW_EXITS))
      ending = _f(row.get(ROW_ENDING))
      avg = _f(row.get(ROW_AVG_FTE))

      expect_end = max(0.0, opening + hires - exits)
      if abs(ending - expect_end) > 0.0001:
        breaks.append(
          "%s Q%s: ending %.4f != opening %.4f + hires %.4f - exits %.4f"
          % (name, q, ending, opening, hires, exits))
      if abs(opening - prev_ending) > 0.0001:
        breaks.append(
          "%s Q%s: opening %.4f != previous ending %.4f"
          % (name, q, opening, prev_ending))
      if abs(avg - ((opening + ending) / 2.0)) > 0.0001:
        breaks.append(
          "%s Q%s: average paid FTE %.4f != (opening %.4f + ending %.4f) / 2"
          % (name, q, avg, opening, ending))
      if g.get("is_owner") and exits > 0:
        breaks.append("%s Q%s: an owner group carries an exit" % (name, q))
      prev_ending = ending
  return breaks


def payroll_by_quarter(grid: Dict[str, Any]) -> Dict[int, float]:
  """What the income statement must carry: the sum of the group totals."""
  return {
    int(t["quarter_index"]): _f(t.get(ROW_TOTAL))
    for t in ((grid or {}).get("totals") or [])
  }


def ending_fte_by_quarter(grid: Dict[str, Any]) -> Dict[int, float]:
  """The denominator for every per-employee ratio, per period - never a
  headcount frozen at year one."""
  return {
    int(t["quarter_index"]): _f(t.get("ending_fte"))
    for t in ((grid or {}).get("totals") or [])
  }


def apply_executive_design(
  grid_groups: Sequence[Dict[str, Any]],
  team_directive: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  """HOW THE EXECUTIVE DEALS WITH IT.

  It used to emit `team: {annual_payroll: 431000}` - a number with no home,
  which is why it never landed. Here it says what it already reasons in prose
  ("headcount reduction from 8 to roughly five"): hires and exits, per group,
  per quarter. Those change Ending FTE, which changes every later quarter, so
  there is no advisory channel to drop it into.
  """
  out = [copy.deepcopy(g) for g in (grid_groups or [])]
  if not isinstance(team_directive, dict):
    return out
  by_name = {str(g.get("group_name") or "").strip().casefold(): g for g in out}
  for design in (team_directive.get("groups") or []):
    if not isinstance(design, dict):
      continue
    target = by_name.get(str(design.get("group") or "").strip().casefold())
    if target is None:
      continue
    for key, field in ((ROW_HIRES, "hires_q"), (ROW_EXITS, "exits_q")):
      moves = design.get(field)
      if not isinstance(moves, dict):
        continue
      slot = "planned_hires" if field == "hires_q" else "planned_exits"
      merged = dict(target.get(slot) or {})
      for q, n in moves.items():
        merged[str(int(q))] = _f(n)
      target[slot] = merged
  return out
