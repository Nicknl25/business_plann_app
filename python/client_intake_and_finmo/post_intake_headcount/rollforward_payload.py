"""THE ROLL-FORWARD AT THE ONE DOOR EVERY PAYROLL PAYLOAD IS BUILT THROUGH.

``rollforward.py`` is the engine Nick specced from the Command Investigations
Headcount tab. This is the wiring. It takes the payload the author produced -
one row per role per quarter, with OEWS wages already resolved - re-expresses
it as position GROUPS rolled forward from her opening team, and writes the
group blocks BACK into ``payload["rows"]``. Every downstream surface (the
model input, finmo, the realism gate, the workbook, the written plan) then
reads a roll-forward, and nothing reads a percentage.

WHAT IS PRESERVED, EXACTLY (Nick: "keep OEWS exactly as it is")
  * OEWS wages. A group's average annual salary is the FTE-weighted mean of
    the wages the author resolved for its rows, taken at the quarter where
    the policy's wage-inflation factor is 1.0 (Q1), so the dollars are the
    author's dollars.
  * The 3% raise. It is the SAME rule the policy already applied
    (``annual_wage_inflation_rate``, year offset ``(q-1)//4``): year one
    flat, a step at Q5/Q9/Q13/Q17. What changes is that it is now a named,
    editable assumption instead of a factor buried in a wage helper.
  * Her opening team. Q1 opening FTE is the authored Q1 starting FTE, so the
    stated-payroll reconciliation sees the same year one it saw before.

WHAT CHANGES
  * FTE moves by HIRES and EXITS, never by a multiplier. An exit is a real
    channel for the first time. ``_enforce_forward_fte_continuity`` clamps
    every authored decrease away (``ending = max(ending, starting)``), which
    is why the executive's "headcount reduction from eight to roughly five"
    could never land on a payroll row. The executive's design is applied
    HERE, after that clamp, straight onto the group it names.
  * The percentage is an OUTPUT. Nothing in this module reads
    ``target_payroll_percent_of_revenue``; it computes payroll as
    average paid FTE x average annual salary / 4, plus burden.
  * The burden rate and the raise are single assumptions the workbook can
    expose as live cells, because the whole grid is derived from them.

NAMED PEOPLE ARE NOT MERGED. A person the client named is her own group -
her identity carries into the written plan and the "named people at 1.0"
doctrine depends on it. The GROUPING Nick asked for ("groups where possible,
not one per person") is the supporting block: six artisans are one group,
not six blocks.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import rollforward as RF

logger = logging.getLogger(__name__)

ROLLFORWARD_PAYLOAD_KEY = "rollforward"
CONTRACT_VERSION = "payroll_fte_rollforward_v1"

# The snake_case names the payload carries. The workbook renders the client's
# labels from RF.BLOCK_ROWS; the payload stays machine-shaped so the payroll
# payload's no-prose validator has nothing to object to.
FIELD_BY_BLOCK_ROW: Dict[str, str] = {
  RF.ROW_OPENING: "opening_fte",
  RF.ROW_HIRES: "hires",
  RF.ROW_EXITS: "exits",
  RF.ROW_ENDING: "ending_fte",
  RF.ROW_AVG_FTE: "average_paid_fte",
  RF.ROW_AVG_SALARY: "average_annual_salary",
  RF.ROW_CASH_COMP: "cash_compensation",
  RF.ROW_TAXES: "payroll_taxes_benefits",
  RF.ROW_TOTAL: "total_employment_cost",
}

_TEMPLATE_FIELDS = (
  "staffing_class",
  "position_title",
  "person_name",
  "oews_occ_title",
  "oews_occ_code",
  "oews_matched_title",
  "oews_match_basis",
  "wage_source",
  "wage_source_code",
  "person_id",
)

_OWNER_TITLE_TOKENS = ("owner", "founder", "co-founder", "principal", "ceo", "president")


def _f(value: Any, default: float = 0.0) -> float:
  try:
    if value is None or isinstance(value, bool):
      return default
    return float(value)
  except (TypeError, ValueError):
    return default


def _money(value: Any) -> int:
  return int(round(_f(value)))


def _norm_key(value: Any) -> str:
  return " ".join(str(value or "").strip().lower().replace("-", " ").split())


def _is_owner_label(*labels: Any) -> bool:
  for label in labels:
    text = _norm_key(label)
    if not text:
      continue
    tokens = set(text.split())
    if any(token in tokens for token in ("owner", "founder", "principal", "ceo", "president")):
      return True
    if "co founder" in text or "cofounder" in text:
      return True
  return False


def _group_identity(row: Dict[str, Any]) -> Tuple[Tuple[str, str], str]:
  """(identity, human label) for the group this row belongs to."""
  staffing_class = str(row.get("staffing_class") or "supporting_staff").strip().lower()
  staffing_class = staffing_class or "supporting_staff"
  if staffing_class == "key_person":
    person = str(row.get("person_name") or "").strip()
    title = str(row.get("position_title") or "").strip()
    return ("key_person", _norm_key(person or title)), (title or person)
  label = str(
    row.get("position_title")
    or row.get("oews_occ_title")
    or row.get("oews_matched_title")
    or ""
  ).strip()
  return ("supporting_staff", _norm_key(label)), label


def groups_from_payload_rows(
  rows: Sequence[Dict[str, Any]],
  *,
  horizon: int,
  annual_salary_increase: float = 0.03,
  team_groups: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
  """Read the authored rows as position groups.

  Returns ``(groups, templates_by_group_name, trace)``. ``groups`` is the
  input to ``RF.build_group_rollforward``; ``templates`` carries each group's
  identity fields (title, OEWS match, wage source) so the rows written back
  are the author's rows with a roll-forward body.
  """
  horizon = max(1, int(horizon or 0))
  rate = _f(annual_salary_increase, 0.03)

  order: List[Tuple[str, str]] = []
  labels: Dict[Tuple[str, str], str] = {}
  by_group: Dict[Tuple[str, str], Dict[int, Dict[str, float]]] = {}
  templates: Dict[Tuple[str, str], Dict[str, Any]] = {}
  template_weight: Dict[Tuple[str, str], float] = {}

  for row in rows or []:
    if not isinstance(row, dict):
      continue
    quarter = int(_f(row.get("quarter_index")) or 0)
    if quarter < 1 or quarter > horizon:
      continue
    identity, label = _group_identity(row)
    if not identity[1]:
      continue
    if identity not in by_group:
      order.append(identity)
      by_group[identity] = {}
      labels[identity] = label
    bucket = by_group[identity].setdefault(
      quarter, {"start": 0.0, "end": 0.0, "wage_num": 0.0, "wage_den": 0.0, "burden": 0.0})
    start = round(_f(row.get("starting_fte")), 4)
    end = round(_f(row.get("ending_fte")), 4)
    wage = _f(row.get("annual_wage"))
    bucket["start"] += start
    bucket["end"] += end
    weight = end if end > 0 else start
    if wage > 0 and weight > 0:
      bucket["wage_num"] += wage * weight
      bucket["wage_den"] += weight
    elif wage > 0 and bucket["wage_den"] <= 0:
      # a quarter with no FTE but a resolved wage still tells us the rate
      bucket["wage_num"] += wage
      bucket["wage_den"] += 1.0
    bucket["burden"] = max(bucket["burden"], _f(row.get("payroll_taxes_benefits_percent")))
    if weight >= template_weight.get(identity, -1.0):
      template_weight[identity] = weight
      templates[identity] = {
        field: copy.deepcopy(row.get(field))
        for field in _TEMPLATE_FIELDS
        if row.get(field) not in (None, "")
      }

  groups: List[Dict[str, Any]] = []
  templates_by_name: Dict[str, Dict[str, Any]] = {}
  group_trace: List[Dict[str, Any]] = []
  used_names: Dict[str, int] = {}

  for identity in order:
    quarters = by_group[identity]
    label = labels.get(identity) or identity[1]
    is_owner = identity[0] == "key_person" and _is_owner_label(
      label, (templates.get(identity) or {}).get("position_title"))

    # THE BASE SALARY IS A Q1 SALARY. The policy's wage inflation factor is
    # 1.0 at Q1 ((q-1)//4 == 0), so a Q1 wage is the base by definition. A
    # group that only starts later is de-inflated back to its Q1 equivalent,
    # or the raise would be applied twice to it.
    base_salary = 0.0
    salary_quarter = 0
    for quarter in sorted(quarters):
      bucket = quarters[quarter]
      if bucket["wage_den"] > 0:
        weighted = bucket["wage_num"] / bucket["wage_den"]
        year_offset = max(0, (quarter - 1) // RF.QUARTERS_PER_YEAR)
        base_salary = weighted / ((1.0 + rate) ** year_offset) if rate else weighted
        salary_quarter = quarter
        break

    opening = round(_f((quarters.get(1) or {}).get("start")), 4)
    hires: Dict[str, float] = {}
    exits: Dict[str, float] = {}
    previous = opening
    for quarter in range(1, horizon + 1):
      bucket = quarters.get(quarter)
      target = previous if bucket is None else round(_f(bucket.get("end")), 4)
      delta = round(target - previous, 4)
      if delta > 1e-6:
        hires[str(quarter)] = delta
        previous = round(previous + delta, 4)
      elif delta < -1e-6 and not is_owner:
        exits[str(quarter)] = round(-delta, 4)
        previous = round(previous + delta, 4)
      # an owner group cannot carry an exit, so its FTE simply holds

    name = label or identity[1]
    if _norm_key(name) in used_names:
      person = str((templates.get(identity) or {}).get("person_name") or "").strip()
      name = f"{name} ({person})" if person else f"{name} {used_names[_norm_key(name)] + 1}"
    used_names[_norm_key(name)] = used_names.get(_norm_key(name), 0) + 1

    groups.append({
      "group_name": name,
      "opening_fte": opening,
      "average_annual_salary": round(base_salary, 2),
      "is_owner": bool(is_owner),
      "planned_hires": hires,
      "planned_exits": exits,
    })
    templates_by_name[name] = templates.get(identity) or {}
    group_trace.append({
      "group_name": name,
      "staffing_class": identity[0],
      "opening_fte": opening,
      "average_annual_salary": round(base_salary, 2),
      "salary_read_at_quarter": salary_quarter,
      "source_row_count": len(quarters),
    })

  rename_trace = _rename_supporting_groups(groups, templates_by_name, team_groups)

  trace: Dict[str, Any] = {"groups": group_trace}
  if rename_trace:
    trace["client_group_names"] = rename_trace
  return groups, templates_by_name, trace


def _rename_supporting_groups(
  groups: List[Dict[str, Any]],
  templates_by_name: Dict[str, Dict[str, Any]],
  team_groups: Optional[Sequence[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
  """Her words on the group, where she gave them.

  The intake asks one question about group composition. When she answers,
  a stated group whose headcount matches a supporting group's opening FTE
  takes that group's name - so the sheet says "Shop crew", not "Welders,
  Cutters, Solderers, and Brazers". The match is arithmetic (headcount),
  never a reading of her sentence: unmatched groups keep the author's
  title and the trace says so.
  """
  stated = [g for g in (team_groups or []) if isinstance(g, dict)]
  if not stated:
    return None
  supporting = [
    g for g in groups
    if str((templates_by_name.get(g["group_name"]) or {}).get("staffing_class")
           or "supporting_staff").strip().lower() != "key_person"
  ]
  matched: List[Dict[str, Any]] = []
  unmatched_stated: List[str] = []
  taken: set = set()
  for item in stated:
    name = str(item.get("group_name") or item.get("name") or "").strip()
    if not name:
      continue
    headcount = _f(item.get("headcount") or item.get("people") or item.get("fte"))
    hit = None
    for group in supporting:
      if id(group) in taken:
        continue
      if headcount > 0 and abs(_f(group.get("opening_fte")) - headcount) <= 0.51:
        hit = group
        break
    if hit is None:
      unmatched_stated.append(name)
      continue
    taken.add(id(hit))
    old = hit["group_name"]
    hit["group_name"] = name
    templates_by_name[name] = templates_by_name.pop(old, {})
    matched.append({"stated_group": name, "authored_group": old, "headcount": headcount})
  if not matched and not unmatched_stated:
    return None
  return {
    "renamed": matched,
    "stated_without_a_matching_group": unmatched_stated,
    "stated_group_count": len(stated),
  }


def rows_from_grid(
  grid: Dict[str, Any],
  *,
  templates_by_name: Dict[str, Dict[str, Any]],
  burden_rate: float,
) -> List[Dict[str, Any]]:
  """One payload row per group per quarter, the block's own numbers.

  The money is computed from the row's OWN 2-dp FTE and whole-dollar
  salary, so the workbook's ``=ROUND(avg*salary/4,0)`` lands on the same
  dollar and "income-statement payroll == sum of group totals" is an
  identity rather than a tolerance.
  """
  burden = round(max(0.0, _f(burden_rate, 0.22)), 2)
  out: List[Dict[str, Any]] = []
  for group in (grid.get("groups") or []):
    name = str(group.get("group_name") or "").strip()
    template = copy.deepcopy(templates_by_name.get(name) or {})
    for quarter_row in (group.get("quarters") or []):
      quarter = int(_f(quarter_row.get("quarter_index")) or 0)
      start = round(_f(quarter_row.get(RF.ROW_OPENING)), 2)
      hires = round(_f(quarter_row.get(RF.ROW_HIRES)), 2)
      exits = round(_f(quarter_row.get(RF.ROW_EXITS)), 2)
      ending = round(start + hires - exits, 2)
      average = round((start + ending) / 2.0, 2)
      wage = _money(quarter_row.get(RF.ROW_AVG_SALARY))
      cash = _money(average * wage / float(RF.QUARTERS_PER_YEAR))
      taxes = _money(cash * burden)
      row = {
        **template,
        "quarter_index": quarter,
        "group_name": name,
        "starting_fte": start,
        "hires": hires,
        "exits": exits,
        "ending_fte": ending,
        "average_fte": average,
        "annual_wage": wage,
        "payroll_taxes_benefits_percent": burden,
        "quarterly_wage_cost": cash,
        "quarterly_taxes_benefits": taxes,
        "total_quarterly_payroll": int(cash + taxes),
      }
      row.setdefault("staffing_class", "supporting_staff")
      out.append(row)
  out.sort(key=lambda r: (int(r.get("quarter_index") or 0), str(r.get("group_name") or "")))
  return out


def _grid_for_payload(
  grid: Dict[str, Any],
  rows: Sequence[Dict[str, Any]],
  *,
  burden_rate: float,
  annual_salary_increase: float,
  raise_quarter_in_year: int,
  horizon: int,
) -> Dict[str, Any]:
  """The grid as the payload carries it: snake_case, numeric, one truth.

  The blocks are rebuilt from the ROWS, not from the engine's cent-level
  arithmetic, so the sheet and the income statement cannot disagree by a
  rounding flutter.
  """
  rows_by_group: Dict[str, Dict[int, Dict[str, Any]]] = {}
  for row in rows:
    rows_by_group.setdefault(str(row.get("group_name") or ""), {})[
      int(_f(row.get("quarter_index")) or 0)] = row
  out_groups: List[Dict[str, Any]] = []
  for group in (grid.get("groups") or []):
    name = str(group.get("group_name") or "").strip()
    quarters: List[Dict[str, Any]] = []
    for quarter in range(1, horizon + 1):
      row = (rows_by_group.get(name) or {}).get(quarter)
      if row is None:
        continue
      quarters.append({
        "quarter_index": quarter,
        "opening_fte": round(_f(row.get("starting_fte")), 2),
        "hires": round(_f(row.get("hires")), 2),
        "exits": round(_f(row.get("exits")), 2),
        "ending_fte": round(_f(row.get("ending_fte")), 2),
        "average_paid_fte": round(_f(row.get("average_fte")), 2),
        "average_annual_salary": _money(row.get("annual_wage")),
        "cash_compensation": _money(row.get("quarterly_wage_cost")),
        "payroll_taxes_benefits": _money(row.get("quarterly_taxes_benefits")),
        "total_employment_cost": _money(row.get("total_quarterly_payroll")),
      })
    stub = (group.get("stub") or {})
    out_groups.append({
      "group_name": name,
      "is_owner": bool(group.get("is_owner")),
      "opening_fte": round(_f(stub.get(RF.ROW_ENDING)), 2),
      "average_annual_salary": _money(stub.get(RF.ROW_AVG_SALARY)),
      "quarters": quarters,
    })
  totals: List[Dict[str, Any]] = []
  for quarter in range(1, horizon + 1):
    ending = cash = taxes = total = 0.0
    for out_group in out_groups:
      for quarter_row in out_group["quarters"]:
        if quarter_row["quarter_index"] != quarter:
          continue
        ending += _f(quarter_row["ending_fte"])
        cash += _f(quarter_row["cash_compensation"])
        taxes += _f(quarter_row["payroll_taxes_benefits"])
        total += _f(quarter_row["total_employment_cost"])
    totals.append({
      "quarter_index": quarter,
      "ending_fte": round(ending, 2),
      "cash_compensation": int(round(cash)),
      "payroll_taxes_benefits": int(round(taxes)),
      "total_employment_cost": int(round(total)),
    })
  return {
    "contract_version": CONTRACT_VERSION,
    "cadence": "quarterly",
    "horizon_quarters": horizon,
    "payroll_tax_and_benefit_burden": round(_f(burden_rate, 0.22), 4),
    "annual_salary_increase": round(_f(annual_salary_increase, 0.03), 4),
    "raise_quarter_in_year": int(raise_quarter_in_year or 1),
    "groups": out_groups,
    "totals": totals,
  }


def identities_from_payload_rows(rows: Sequence[Dict[str, Any]]) -> List[str]:
  """The three FTE identities, read off the payload the run will ship.

  ending == opening + hires - exits; opening[q] == ending[q-1]; average paid
  FTE == (opening + ending) / 2. Step 4 of the directive checks these every
  period, so they are readable from the payload without the engine.
  """
  broken: List[str] = []
  by_group: Dict[str, Dict[int, Dict[str, Any]]] = {}
  for row in rows or []:
    if not isinstance(row, dict):
      continue
    by_group.setdefault(str(row.get("group_name") or ""), {})[
      int(_f(row.get("quarter_index")) or 0)] = row
  for name, quarter_rows in by_group.items():
    previous_ending: Optional[float] = None
    for quarter in sorted(quarter_rows):
      row = quarter_rows[quarter]
      opening = round(_f(row.get("starting_fte")), 2)
      hires = round(_f(row.get("hires")), 2)
      exits = round(_f(row.get("exits")), 2)
      ending = round(_f(row.get("ending_fte")), 2)
      average = round(_f(row.get("average_fte")), 2)
      if abs((opening + hires - exits) - ending) > 0.01:
        broken.append(
          "%s Q%d: ending %.2f != opening %.2f + hires %.2f - exits %.2f"
          % (name, quarter, ending, opening, hires, exits))
      if previous_ending is not None and abs(opening - previous_ending) > 0.01:
        broken.append("%s Q%d: opening %.2f != prior ending %.2f"
                      % (name, quarter, opening, previous_ending))
      if abs(average - round((opening + ending) / 2.0, 2)) > 0.01:
        broken.append("%s Q%d: average paid FTE %.2f != (%.2f + %.2f) / 2"
                      % (name, quarter, average, opening, ending))
      previous_ending = ending
  return broken


def normalize_payload_to_group_rollforward(
  payload: Optional[Dict[str, Any]],
  *,
  horizon: int,
  annual_salary_increase: float = 0.03,
  raise_quarter_in_year: int = 1,
  people_json: Optional[Dict[str, Any]] = None,
  team_directive: Optional[Dict[str, Any]] = None,
  draft_id: Any = "",
) -> Optional[Dict[str, Any]]:
  """Re-express ``payload["rows"]`` as a group roll-forward, in place.

  Returns the trace it stamps on the payload, or None when there is nothing
  to roll forward (no rows). Mutates ``payload``: ``rows``, ``quarter_totals``
  and ``rollforward`` are replaced together, so no surface can read half of
  the change.
  """
  if not isinstance(payload, dict):
    return None
  rows = [r for r in (payload.get("rows") or []) if isinstance(r, dict)]
  if not rows:
    return None
  horizon = max(1, int(horizon or 0))

  burden_values = [
    _f(r.get("payroll_taxes_benefits_percent")) for r in rows
    if _f(r.get("payroll_taxes_benefits_percent")) > 0
  ]
  weighted_burden = 0.0
  weight_total = 0.0
  for row in rows:
    if int(_f(row.get("quarter_index")) or 0) != 1:
      continue
    weight = max(0.0, _f(row.get("ending_fte")))
    burden = _f(row.get("payroll_taxes_benefits_percent"))
    if weight > 0 and burden > 0:
      weighted_burden += burden * weight
      weight_total += weight
  burden_rate = round(
    (weighted_burden / weight_total) if weight_total > 0
    else (max(burden_values) if burden_values else 0.22), 2)
  burden_spread = (
    round(max(burden_values) - min(burden_values), 4) if burden_values else 0.0)

  team_groups = None
  if isinstance(people_json, dict):
    candidate = people_json.get("team_groups")
    if isinstance(candidate, list):
      team_groups = candidate

  groups, templates_by_name, read_trace = groups_from_payload_rows(
    rows,
    horizon=horizon,
    annual_salary_increase=annual_salary_increase,
    team_groups=team_groups,
  )
  if not groups:
    return None

  directive = team_directive
  if directive is None:
    directive = _active_team_directive(draft_id)
  design_trace = None
  if isinstance(directive, dict) and directive.get("groups"):
    before = [copy.deepcopy(g) for g in groups]
    missing = _unmatched_design_groups(groups, directive)
    groups = RF.apply_executive_design(groups, directive)
    design_trace = _design_trace(before, groups)
    if missing:
      design_trace["named_groups_not_found"] = missing
      logger.error(
        "PAYROLL_ROLLFORWARD_DESIGN_NAMES_UNKNOWN_GROUP draft=%s named=%s have=%s",
        str(draft_id or "")[:8], missing,
        [str(g.get("group_name")) for g in groups][:8])

  grid = RF.build_group_rollforward(
    groups=groups,
    horizon_quarters=horizon,
    burden_rate=burden_rate,
    annual_salary_increase=annual_salary_increase,
    raise_quarter_in_year=raise_quarter_in_year,
  )
  engine_broken = RF.identities(grid)
  new_rows = rows_from_grid(
    grid, templates_by_name=templates_by_name, burden_rate=burden_rate)
  if not new_rows:
    return None
  payload_broken = identities_from_payload_rows(new_rows)

  quarter_payroll: Dict[int, int] = {}
  quarter_ending: Dict[int, float] = {}
  for row in new_rows:
    quarter = int(_f(row.get("quarter_index")) or 0)
    quarter_payroll[quarter] = quarter_payroll.get(quarter, 0) + int(
      _f(row.get("total_quarterly_payroll")))
    quarter_ending[quarter] = round(
      quarter_ending.get(quarter, 0.0) + _f(row.get("ending_fte")), 2)

  before_payroll = {
    int(_f(item.get("quarter_index")) or 0): int(_f(item.get("payroll")))
    for item in (payload.get("quarter_totals") or []) if isinstance(item, dict)
  }

  payload["rows"] = new_rows
  payload["quarter_totals"] = [
    {
      "quarter_index": quarter,
      "ending_fte": round(quarter_ending.get(quarter, 0.0), 2),
      "payroll": int(quarter_payroll.get(quarter, 0)),
    }
    for quarter in range(1, horizon + 1)
  ]
  payload[ROLLFORWARD_PAYLOAD_KEY] = _grid_for_payload(
    grid, new_rows,
    burden_rate=burden_rate,
    annual_salary_increase=annual_salary_increase,
    raise_quarter_in_year=raise_quarter_in_year,
    horizon=horizon,
  )

  year_one_before = sum(before_payroll.get(q, 0) for q in (1, 2, 3, 4))
  year_one_after = sum(quarter_payroll.get(q, 0) for q in (1, 2, 3, 4))
  trace: Dict[str, Any] = {
    "applied": True,
    "group_count": len(groups),
    "row_count": len(new_rows),
    "payroll_tax_and_benefit_burden": burden_rate,
    "burden_rate_spread_across_rows": burden_spread,
    "annual_salary_increase": round(_f(annual_salary_increase, 0.03), 4),
    "year_one_payroll_before": int(year_one_before),
    "year_one_payroll_after": int(year_one_after),
    **read_trace,
  }
  if design_trace:
    trace["executive_design"] = design_trace
  if engine_broken or payload_broken:
    # An identity break is a build bug, not a client outcome. It is stamped
    # (the realism gate and the acceptance verdict both read this payload)
    # rather than swallowed.
    trace["identity_breaks"] = (engine_broken + payload_broken)[:10]
    logger.error(
      "PAYROLL_ROLLFORWARD_IDENTITY_BREAK draft=%s breaks=%s",
      str(draft_id or "")[:8], (engine_broken + payload_broken)[:3])
  payload["payroll_rollforward"] = trace
  logger.info(
    "PAYROLL_ROLLFORWARD_APPLIED draft=%s groups=%d rows=%d burden=%.2f "
    "raise=%.2f year1_before=%d year1_after=%d",
    str(draft_id or "")[:8], len(groups), len(new_rows), burden_rate,
    _f(annual_salary_increase), int(year_one_before), int(year_one_after))
  return trace


def _design_trace(
  before: Sequence[Dict[str, Any]],
  after: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
  landed: List[Dict[str, Any]] = []
  by_name_before = {str(g.get("group_name") or ""): g for g in before}
  for group in after:
    name = str(group.get("group_name") or "")
    was = by_name_before.get(name) or {}
    exits_before = sum(_f(v) for v in (was.get("planned_exits") or {}).values())
    exits_after = sum(_f(v) for v in (group.get("planned_exits") or {}).values())
    hires_before = sum(_f(v) for v in (was.get("planned_hires") or {}).values())
    hires_after = sum(_f(v) for v in (group.get("planned_hires") or {}).values())
    if abs(exits_after - exits_before) > 1e-6 or abs(hires_after - hires_before) > 1e-6:
      landed.append({
        "group_name": name,
        "exits_added": round(exits_after - exits_before, 2),
        "hires_added": round(hires_after - hires_before, 2),
      })
  return {"groups_changed": landed, "changed_group_count": len(landed)}


def _unmatched_design_groups(
  groups: Sequence[Dict[str, Any]],
  directive: Optional[Dict[str, Any]],
) -> List[str]:
  """A design that names a group we do not have is NOT silently dropped.

  ``apply_executive_design`` matches on the group name; an executive naming
  "studio artisans" where the author's block is "Glass artisans" changes
  nothing, and that is the exact shape of the defect this replaces. The
  names it could not find are stamped on the payload.
  """
  have = {str(g.get("group_name") or "").strip().casefold() for g in (groups or [])}
  missing: List[str] = []
  for design in ((directive or {}).get("groups") or []):
    if not isinstance(design, dict):
      continue
    named = str(design.get("group") or "").strip()
    if named and named.casefold() not in have:
      missing.append(named)
  return missing


def _active_team_directive(draft_id: Any) -> Optional[Dict[str, Any]]:
  """The executive's restructure design, if a loop is live for this draft.

  Best-effort: the registry is process memory populated only by the
  restructure stage, so a normal run finds nothing and this is a no-op.
  """
  key = str(draft_id or "").strip()
  if not key:
    return None
  try:
    from client_intake_and_finmo.post_intake_restructure.registry import (  # type: ignore
      get_active_directive,
    )
  except Exception:
    return None
  try:
    directive = get_active_directive(key)
  except Exception:
    return None
  if not isinstance(directive, dict):
    return None
  team = directive.get("team")
  if isinstance(team, dict) and team.get("groups"):
    return team
  return None
