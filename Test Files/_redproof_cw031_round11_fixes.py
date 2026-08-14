"""CW-031 round 11 -- the GREEN half: mini's round-10 D1/D2/D3 fixes, proven
on the real module.

D1  A match never names an ambiguous field: when a stated figure sits under
    TWO OR MORE distinct leaf names, the match fires with leaf None and the
    sentence speaks the bare value; exactly one distinct name -> named as
    before (the common case is untouched).
D2  A near-miss never claims a match: the tolerance is float dust only,
    max(0.5, 1e-9*|v|). A sub-0.5% CORRECTION is no longer swallowed as a
    confirmation.
D3  Group identity is the stored member set, not the label string: the
    coherence pass partitions carrying rows by member frozenset, so a label
    collision cannot kill two healthy groups and a stale legacy row retires
    ALONE instead of dragging a fresh declaration down with it.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round11_fixes.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers.intake_consult import (  # type: ignore
  _apply_per_line_cogs_patch_keys,
  _figures_all_on_file,
  _spoken_on_file_match,
)

RESULTS = []


def check(tag: str, ok: bool, detail: str = "") -> None:
  RESULTS.append(ok)
  print(f"[{'PASS' if ok else 'FAIL'}] {tag}" + (f" -- {detail}" if detail else ""))


def ops(names_rates):
  return {"lob_models": [{
    "lob_name": "Main",
    "products": [
      {"product_name": n, "cogs_percent_of_line_revenue": r,
       "unit_price": 100.0, "units_per_period_capacity": 10.0,
       "operating_periods_per_year": 12.0}
      for n, r in names_rates
    ],
  }]}


def prows(o):
  return o["lob_models"][0]["products"]


# ---- D1 ---------------------------------------------------------------------
state = {"financials": {"monthly_rent_expense": 9800.0,
                        "annual_interest_payment": 9800.0,
                        "current_revenue": 1553000.0}}
m = _figures_all_on_file(state, [9800.0])
spoken = _spoken_on_file_match(*m[0]) if m else "(no match)"
check("1a ambiguous value: match fires with NO field claim",
      bool(m) and m[0][0] is None and "9,800" in spoken and " is " not in spoken,
      f"m={m!r} spoken={spoken!r}")

m = _figures_all_on_file(state, [1553000.0])
spoken = _spoken_on_file_match(*m[0]) if m else "(no match)"
check("1b unique leaf name: named as today",
      bool(m) and m[0][0] == "current_revenue"
      and spoken == "current revenue is $1,553,000",
      f"m={m!r} spoken={spoken!r}")

state_same = {"financials": {"roles": [
  {"annual_wage": 96000.0}, {"annual_wage": 96000.0}]}}
m = _figures_all_on_file(state_same, [96000.0])
check("1c same name twice: still named (distinct-name rule, not leaf count)",
      bool(m) and m[0][0] == "annual_wage", f"m={m!r}")

# ---- D2 ---------------------------------------------------------------------
state2 = {"financials": {"current_revenue": 1553000.0}}
exact = _figures_all_on_file(state2, [1553000.0])
dust = _figures_all_on_file(state2, [1552999.999999999])
check("2a exact and float-dust restatements match",
      bool(exact) and bool(dust), f"exact={bool(exact)} dust={bool(dust)}")
check("2b a 0.32% correction never claims a match",
      not _figures_all_on_file(state2, [1548000.0]))
check("2c a 0.45% correction never claims a match",
      not _figures_all_on_file(state2, [1546000.0]))

# ---- D3 ---------------------------------------------------------------------
# 3a label collision: 'A+B','C' and 'A','B+C' both label shared:a+b+c.
o1 = ops([("A+B", 0.30), ("C", 0.30), ("A", 0.50), ("B+C", 0.50)])
_apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["A+B", "C"]]}, ops_json=o1)
r1 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["A", "B+C"]]}, ops_json=o1)
g1 = [p.get("cogs_cost_structure_group") for p in prows(o1)]
check("3a label collision: both healthy groups survive",
      all(g1) and not r1.get("ungrouped"),
      f"groups={g1!r} ungrouped={r1.get('ungrouped')!r}")

# 3b stale legacy twin (renamed after grouping) vs fresh declaration.
o2 = ops([("Alpha", 0.40), ("Beta", 0.40), ("Gamma", 0.20)])
a2, b2, g2 = prows(o2)
g2["cogs_cost_structure_group"] = "shared:alpha+beta"
g2["cogs_cost_structure_group_basis"] = "declared"
r2 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["Alpha", "Beta"]]}, ops_json=o2)
check("3b stale legacy twin retires ALONE, fresh declaration survives",
      bool(a2.get("cogs_cost_structure_group"))
      and bool(b2.get("cogs_cost_structure_group"))
      and not g2.get("cogs_cost_structure_group")
      and r2.get("ungrouped") == ["Main / Gamma"],
      f"ungrouped={r2.get('ungrouped')!r}")

# 3c agreeing mixed membership (one row with the list, one legacy) survives.
o3 = ops([("Plum", 0.30), ("Pear", 0.30)])
p3, q3 = prows(o3)
for row in (p3, q3):
  row["cogs_cost_structure_group"] = "shared:pear+plum"
  row["cogs_cost_structure_group_basis"] = "declared"
p3["cogs_cost_structure_group_members"] = ["pear", "plum"]
_apply_per_line_cogs_patch_keys(
  {"financials.cogs_per_line": [
    {"line_name": "Plum", "cogs_percent": 0.31, "unit": "ratio"}]},
  ops_json=o3)
check("3c agreeing mixed group survives",
      bool(p3.get("cogs_cost_structure_group"))
      and bool(q3.get("cogs_cost_structure_group")))

# 3d/3e pure legacy rows (no member lists anywhere under the label): the
# label-parse fallback survives a coherent claim, retires an incoherent one.
o4 = ops([("A", 0.30), ("B", 0.30), ("C", 0.20), ("D", 0.20)])
ra, rb, rc, rd = prows(o4)
for row in (ra, rb):
  row["cogs_cost_structure_group"] = "shared:a+b"
  row["cogs_cost_structure_group_basis"] = "declared"
r4 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["C", "D"]]}, ops_json=o4)
check("3d legacy-only coherent label survives (parse fallback)",
      bool(ra.get("cogs_cost_structure_group"))
      and bool(rb.get("cogs_cost_structure_group")),
      f"ungrouped={r4.get('ungrouped')!r}")

o5 = ops([("A", 0.30), ("B", 0.30), ("C", 0.20), ("D", 0.20)])
ra5, rb5, rc5, rd5 = prows(o5)
for row in (ra5, rb5):
  row["cogs_cost_structure_group"] = "shared:a+b+z"  # z never carries it
  row["cogs_cost_structure_group_basis"] = "declared"
r5 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["C", "D"]]}, ops_json=o5)
check("3e legacy-only incoherent label retires",
      not ra5.get("cogs_cost_structure_group")
      and not rb5.get("cogs_cost_structure_group"),
      f"ungrouped={r5.get('ungrouped')!r}")

# 3f a partition missing a carrying row retires (the O4b shape).
o6 = ops([("P1", 0.30), ("P2", 0.30), ("P3", 0.30), ("P4", 0.10)])
_apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["P1", "P2"]]}, ops_json=o6)
r6 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["P2", "P3", "P4"]]}, ops_json=o6)
check("3f a one-row group wearing a two-member claim retires (O4b shape)",
      not prows(o6)[0].get("cogs_cost_structure_group")
      and "Main / P1" in (r6.get("ungrouped") or []),
      f"ungrouped={r6.get('ungrouped')!r}")

n_fail = sum(1 for ok in RESULTS if not ok)
print("=" * 78)
print(f"{len(RESULTS)} checks, {n_fail} FAIL")
raise SystemExit(1 if n_fail else 0)
